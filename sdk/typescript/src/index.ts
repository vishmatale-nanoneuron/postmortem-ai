/**
 * Airlock TypeScript SDK -- the prompt-injection and exfiltration guard for
 * AI agents, as three calls. Zero dependencies: uses the global `fetch`
 * (Node 18+, Bun, Deno, browsers, edge runtimes).
 *
 *   import { Airlock } from "nanoneuron-airlock";
 *   const guard = new Airlock({ apiKey: "alk_..." });
 *   const result = await guard.scan(untrustedText);
 *   if (result.verdict === "block") { ... }
 *
 * Every call is paid from the key's prepaid credits (1 per scan or egress
 * check, 2 per proxy fetch, +4 for a deep scan). Every non-200 throws an
 * AirlockError subclass, so a caller that treats "any throw = block" fails
 * closed. Nothing is retried automatically: a retried scan is a second charge.
 */

export const DEFAULT_BASE_URL = "https://postmortem-ai-api.vercel.app";
export const VERSION = "0.1.0";

export type Verdict = "allow" | "flag" | "block";

export type Match = { rule_id: string; family: string; weight: number; description: string };

export type Semantic = {
  status: "ok" | "unavailable" | "skipped";
  injection?: boolean;
  confidence?: number;
  family?: string | null;
  reason: string;
  model?: string;
  weight: number;
};

export type Policy = { block_threshold: number; flag_threshold: number; muted_rules: string[]; default: boolean };

export type ScanResult = {
  verdict: Verdict;
  score: number;
  matches: Match[];
  families: string[];
  signals: Record<string, unknown>;
  content_sha256: string;
  content_bytes: number;
  latency_ms: number;
  credits_remaining: number | null;
  credits_charged: number;
  semantic: Semantic | null;
  sanitized: string | null;
  policy: Policy;
  /** Correlation id from the X-Request-ID header; quote it when asking about a call. */
  request_id: string | null;
};

export type EgressResult = {
  verdict: Verdict;
  score: number;
  reasons: string[];
  secrets_found: string[];
  pii_found: Record<string, number>;
  destination: string | null;
  destination_checked: boolean;
  redacted: string | null;
  credits_remaining: number | null;
  credits_charged: number;
  request_id: string | null;
};

export type FetchResult = {
  verdict: Verdict;
  score: number;
  stage: "egress" | "ingress";
  reasons: string[];
  matches: Match[];
  families: string[];
  signals: Record<string, unknown>;
  url: string;
  final_url: string | null;
  http_status: number | null;
  content_type: string | null;
  content_bytes: number;
  content_sha256: string | null;
  destination_checked: boolean;
  hops: number;
  truncated: boolean;
  fetch_ms: number;
  latency_ms: number;
  content: string | null;
  credits_remaining: number | null;
  credits_charged: number;
  semantic: Semantic | null;
  policy: Policy;
  request_id: string | null;
};

export type AccountPolicy = {
  block_threshold: number;
  flag_threshold: number;
  muted_rules: string[];
  egress_allowlist: string[];
  default: boolean;
  updated_at: number | null;
};

export type Usage = {
  days: number;
  total_credits: number;
  rows: { day: string; key_prefix: string | null; scans: number; deep_scans: number; egress: number; refunds: number; credits: number }[];
};

export type Rules = { count: number; families: string[]; rules: Match[] };

/** A report that a verdict was wrong. Only the hash, verdicts and rule ids are stored unless `content` is sent. */
export type Feedback = {
  id: string;
  content_sha256: string;
  kind: "ingress" | "egress";
  verdict_given: Verdict;
  verdict_expected: Verdict;
  rule_ids: string[];
  source: string | null;
  note: string | null;
  has_content: boolean;
  created_at: number;
  request_id: string | null;
};

export type Suggestion = {
  kind: "mute_rule" | "deep_scan_source";
  rule_id: string | null;
  source: string | null;
  reports: number;
  detail: string;
};

export type Tuning = { reports: Feedback[]; suggestions: Suggestion[]; examples_with_content: number; request_id: string | null };

/** Any non-200 from the API. */
export class AirlockError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly requestId: string | null,
  ) {
    super(`${status}: ${detail}`);
    this.name = "AirlockError";
  }
}
/** 401: no key, or an invalid / revoked one. */
export class AuthenticationError extends AirlockError {
  override readonly name = "AuthenticationError";
}
/** 402: the account has no credits left. Nothing was scanned. */
export class InsufficientCredits extends AirlockError {
  override readonly name = "InsufficientCredits";
}
/** 429: `retryAfter` seconds until the window resets. */
export class RateLimited extends AirlockError {
  override readonly name = "RateLimited";
  constructor(status: number, detail: string, requestId: string | null, public readonly retryAfter: number | null) {
    super(status, detail, requestId);
  }
}
/** Proxy fetch: the URL will never be fetched (422) or could not be reached (502). Verdict block; the attempt cost one credit. */
export class FetchRefused extends AirlockError {
  override readonly name = "FetchRefused";
}

export type AirlockOptions = {
  apiKey: string;
  baseUrl?: string;
  /** Milliseconds before a call is abandoned (default 30 000). */
  timeoutMs?: number;
  /** Override `fetch` (tests, custom agents). */
  fetch?: typeof fetch;
};

type Detail = string | { loc?: unknown[]; msg?: string }[];

function describe(detail: Detail | undefined, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => `${(e.loc ?? []).join(".")}: ${e.msg ?? ""}`).join("; ");
  return fallback;
}

export class Airlock {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AirlockOptions) {
    if (!options.apiKey || !options.apiKey.startsWith("alk_")) {
      throw new Error("apiKey must be an Airlock key (starts with 'alk_')");
    }
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchImpl = options.fetch ?? fetch;
  }

  /** Score untrusted text before it reaches the model. 1 credit; 5 with `deep`. */
  scan(content: string, options: { source?: string; deep?: boolean; sanitize?: boolean } = {}): Promise<ScanResult> {
    return this.call<ScanResult>("POST", "/v1/airlock/scan", {
      content,
      source: options.source ?? null,
      deep: options.deep ?? false,
      sanitize: options.sanitize ?? false,
    });
  }

  /** Check an outbound call for credentials, personal data and destination. 1 credit. */
  egress(payload: string, options: { destination?: string; allowlist?: string[] } = {}): Promise<EgressResult> {
    return this.call<EgressResult>("POST", "/v1/airlock/egress", {
      payload,
      destination: options.destination ?? null,
      allowlist: options.allowlist ?? [],
    });
  }

  /** Have Airlock fetch and screen a URL; the page text comes back only if it passes. 2 credits. */
  fetch(url: string, options: { allowlist?: string[]; deep?: boolean; returnContent?: boolean } = {}): Promise<FetchResult> {
    return this.call<FetchResult>(
      "POST",
      "/v1/airlock/proxy/fetch",
      { url, allowlist: options.allowlist ?? [], deep: options.deep ?? false, return_content: options.returnContent ?? true },
      { proxy: true },
    );
  }

  policy(): Promise<AccountPolicy> {
    return this.call<AccountPolicy>("GET", "/v1/airlock/policy");
  }

  usage(days = 30): Promise<Usage> {
    return this.call<Usage>("GET", `/v1/airlock/usage?days=${days}`);
  }

  rules(): Promise<Rules> {
    return this.call<Rules>("GET", "/v1/airlock/rules");
  }

  /**
   * Report that a verdict was wrong: `expected` is what it should have been.
   * Not metered. Pass `content` only to keep the text as a tuning example you
   * can export; by default only the hash is stored. Reports tune the account:
   * see `tuning()`.
   */
  feedback(
    result: ScanResult | FetchResult,
    expected: Verdict,
    options: { note?: string; content?: string; source?: string } = {},
  ): Promise<Feedback> {
    if (!result.content_sha256) {
      throw new Error("this result carries no content hash to report against (the URL was refused before any fetch)");
    }
    return this.call<Feedback>("POST", "/v1/airlock/feedback", {
      content_sha256: result.content_sha256,
      kind: "ingress",
      verdict_given: result.verdict,
      verdict_expected: expected,
      rule_ids: result.matches.map((m) => m.rule_id),
      source: options.source ?? null,
      note: options.note ?? null,
      content: options.content ?? null,
    });
  }

  /** The account's reports, what they suggest (mute a rule, deep-scan a source) and how many carry text. */
  tuning(): Promise<Tuning> {
    return this.call<Tuning>("GET", "/v1/airlock/tuning");
  }

  /** The reports that included text, as JSON lines in the Vertex AI supervised-tuning format. */
  tuningExamples(): Promise<string> {
    return this.call<string>("GET", "/v1/airlock/tuning/export.jsonl", undefined, { text: true });
  }

  private async call<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    flags: { proxy?: boolean; text?: boolean } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: {
          "X-Airlock-Key": this.apiKey,
          "content-type": "application/json",
          "user-agent": `airlock-typescript/${VERSION}`,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    const requestId = response.headers.get("x-request-id");
    if (flags.text && response.ok) return (await response.text()) as T;
    const json = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const detail = describe(json.detail as Detail | undefined, `Request failed: ${response.status}`);
      if (response.status === 401) throw new AuthenticationError(response.status, detail, requestId);
      if (response.status === 402) throw new InsufficientCredits(response.status, detail, requestId);
      if (response.status === 429) {
        const retry = response.headers.get("retry-after");
        throw new RateLimited(response.status, detail, requestId, retry && /^\d+$/.test(retry) ? Number(retry) : null);
      }
      if (flags.proxy && (response.status === 422 || response.status === 502)) {
        throw new FetchRefused(response.status, detail, requestId);
      }
      throw new AirlockError(response.status, detail, requestId);
    }
    return { ...(json as object), request_id: requestId } as T;
  }
}
