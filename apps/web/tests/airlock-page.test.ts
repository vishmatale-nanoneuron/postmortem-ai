import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The /airlock page makes quantitative claims about the engine, and it
// quotes a price. Both are ways a marketing page goes wrong quietly, so
// both are pinned here: the engine numbers against what the code does, and
// the price against the one place the backend defines it.
//
// The numbers below were produced by running Airlock's own code
// (apps/api/app/airlock/rules.py -- 30 rules, 8 families;
// airlock/detector.py -- block 0.75 / flag 0.40; airlock/egress.py -- 11
// credential and 7 PII patterns; airlock/semantic.py -- 5 credits for a
// deep scan). If the rule set grows, this test is what fails, and the page
// must be re-checked against the engine rather than left quoting a stale
// count.
const PAGE = readFileSync(join(__dirname, "..", "app", "airlock", "page.tsx"), "utf8");
const PRICING_DEFAULTS = readFileSync(join(__dirname, "..", "app", "airlock", "pricing-defaults.ts"), "utf8");
const PLAYGROUND = readFileSync(join(__dirname, "..", "app", "airlock", "playground.tsx"), "utf8");
// The backend is the only authority on a price. The frontend's fallback
// constants (used when the live pricing fetch fails at render) must equal
// the backend's settings defaults, or the page can quote a number the API
// would not.
const SETTINGS_PY = readFileSync(join(__dirname, "..", "..", "api", "app", "settings.py"), "utf8");
const SEMANTIC_PY = readFileSync(join(__dirname, "..", "..", "api", "app", "airlock", "semantic.py"), "utf8");
// Airlock copy now also lives on the homepage (the hero and the header), so
// the rules below are checked against every file that carries it -- or the
// front door becomes the one place they are not enforced.
const HERO = readFileSync(join(__dirname, "..", "app", "airlock", "airlock-hero.tsx"), "utf8");
const LANDING = readFileSync(join(__dirname, "..", "app", "landing.tsx"), "utf8");
const HOME_META = readFileSync(join(__dirname, "..", "app", "page.tsx"), "utf8");
const AIRLOCK_COPY = [PAGE, HERO, LANDING, HOME_META];
// Hard-wrapped at ~72 columns, so a phrase that must appear in it can
// straddle a newline. Compared with whitespace collapsed, which is what
// "says the same thing" actually means for a prose file.
const LLMS_FULL = readFileSync(join(__dirname, "..", "public", "llms-full.txt"), "utf8").replace(/\s+/g, " ");

describe("/airlock", () => {
  it("quotes the engine's real counts", () => {
    expect(PAGE).toContain("30 weighted rules across 8 attack families");
    expect(PAGE).toContain("11 credential patterns");
    expect(PAGE).toContain("7 personal-data patterns");
    expect(PAGE).toContain("At 0.75 the verdict is block; at 0.40, flag.");
  });

  it("names every one of the eight families the engine defines", () => {
    for (const family of [
      "Instruction override",
      "Role hijack",
      "Delimiter break",
      "Exfiltration",
      "Tool abuse",
      "Authority spoof",
      "Memory poison",
      "Encoding",
    ]) {
      expect(PAGE).toContain(family);
    }
  });

  it("reports the corpus result as a self-authored smoke test, never as a benchmark", () => {
    expect(PAGE).toContain("43-case corpus we wrote ourselves");
    expect(PAGE).toContain("It is still a smoke test, not a benchmark.");
    // The coverage claim is the one that carries weight, so it is pinned
    // alongside the disclaimer rather than left to drift apart from it.
    expect(PAGE).toContain("every one of the 30 rules is exercised");
    // The words that would turn an 18-case suite into a false accuracy
    // claim. None of them belong on this page until a real benchmark runs.
    for (const forbidden of ["precision rate", "% accurate", "99.", "false-positive rate of", "accuracy of"]) {
      expect(PAGE).not.toContain(forbidden);
    }
  });

  it("quotes exactly the price the backend defines, and nowhere else", () => {
    // Airlock is paid. The page's fallback prices are the backend's own
    // settings defaults -- pinned here by reading settings.py, so a change
    // to AIRLOCK_PACK_PRICE_* on one side without the other fails the build
    // rather than publishing two prices.
    const setting = (name: string) => {
      const match = SETTINGS_PY.match(new RegExp(`${name.toLowerCase()}: int = Field\\(default=([0-9_]+)`));
      if (!match) throw new Error(`settings.py no longer defines ${name}`);
      return Number(match[1]!.replace(/_/g, ""));
    };
    const fallback = (currency: string) => {
      const match = PRICING_DEFAULTS.match(new RegExp(`currency: "${currency}", amount: ([0-9_]+)`));
      if (!match) throw new Error(`pricing-defaults.ts has no ${currency} row`);
      return Number(match[1]!.replace(/_/g, ""));
    };
    expect(fallback("INR")).toBe(setting("airlock_pack_price_inr"));
    expect(fallback("USD")).toBe(setting("airlock_pack_price_usd"));
    expect(fallback("GBP")).toBe(setting("airlock_pack_price_gbp"));
    expect(fallback("EUR")).toBe(setting("airlock_pack_price_eur"));
    expect(Number(PRICING_DEFAULTS.match(/scans_per_pack: ([0-9_]+)/)![1]!.replace(/_/g, ""))).toBe(
      setting("airlock_pack_scans"),
    );
    expect(Number(PRICING_DEFAULTS.match(/max_packs_per_claim: ([0-9_]+)/)![1]!)).toBe(
      setting("airlock_max_packs_per_claim"),
    );
    // Deep scan cost: 1 + DEEP_SCAN_EXTRA_CREDITS from semantic.py.
    const extra = Number(SEMANTIC_PY.match(/DEEP_SCAN_EXTRA_CREDITS = (\d+)/)![1]!);
    expect(Number(PRICING_DEFAULTS.match(/credits_per_deep_scan: (\d+)/)![1]!)).toBe(1 + extra);
    expect(PLAYGROUND).toContain(`Scan it (${1 + extra} credits)`);
    // Proxy fetch cost from proxy.py.
    const PROXY_PY = readFileSync(join(__dirname, "..", "..", "api", "app", "airlock", "proxy.py"), "utf8");
    const proxyCredits = Number(PROXY_PY.match(/PROXY_FETCH_CREDITS = (\d+)/)![1]!);
    expect(Number(PRICING_DEFAULTS.match(/credits_per_proxy_fetch: (\d+)/)![1]!)).toBe(proxyCredits);

    // The FAQ states the price in prose too; keep it equal to the defaults.
    expect(PAGE).toContain(`\\u20b9${setting("airlock_pack_price_inr")} by UPI`);
    expect(PAGE).toContain(`$${setting("airlock_pack_price_usd")} / \\u00a3${setting("airlock_pack_price_gbp")} / \\u20ac${setting("airlock_pack_price_eur")}`);

    // No hardcoded Airlock price anywhere except the defaults file and the
    // FAQ prose that the assertions above pin. Every rendered number comes
    // from the pricing object. (landing.tsx carries PostMortem AI's own
    // "$40,000" example sentence, which is not a price -- so the hero and
    // home metadata are checked for currency literals, and every Airlock
    // file for the per-scan phrasing.)
    for (const source of [HERO, HOME_META]) {
      expect(source).not.toMatch(/[₹$£€]\s?\d/);
    }
    for (const source of [HERO, LANDING, HOME_META]) {
      expect(source).not.toContain("per scan");
    }
    // And no remnant of the invented pricing from the original strategy doc.
    for (const source of AIRLOCK_COPY) {
      expect(source).not.toContain("$0.001");
      expect(source).not.toContain("$2k");
    }
  });

  it("offers nothing for free, anywhere Airlock is mentioned", () => {
    // The user's decision: Airlock is not given away. The pages must not
    // promise a free tier, a free scanner, or a no-signup path -- the
    // playground spends real credits and says so.
    for (const source of [...AIRLOCK_COPY, PLAYGROUND]) {
      expect(source.toLowerCase()).not.toContain("free scanner");
      expect(source.toLowerCase()).not.toContain("free tier for");
      expect(source.toLowerCase()).not.toContain("no signup");
      expect(source.toLowerCase()).not.toContain("free, no");
    }
    expect(PAGE).toContain("no free tier");
    expect(PLAYGROUND).toContain("there is no free tier");
    expect(PLAYGROUND).toContain("402");
  });

  it("puts a price in structured data only because the page makes the same one", () => {
    // `offers` was forbidden while nothing was for sale. Now it is required,
    // and it must be built from the same pricing object the page renders --
    // not a literal -- so a rich result can never show a price the page
    // doesn't.
    expect(PAGE).toContain("offers: pricing.prices");
    expect(PAGE).toContain('"@type": "Offer"');
    expect(PAGE).toContain("priceCurrency: price.currency");
    expect(PAGE).not.toMatch(/price: \d/);
  });

  it("makes no accuracy claim anywhere Airlock is mentioned", () => {
    for (const source of AIRLOCK_COPY) {
      for (const forbidden of ["precision rate", "% accurate", "99.", "false-positive rate of", "accuracy of"]) {
        expect(source).not.toContain(forbidden);
      }
    }
  });

  it("leads the site with Airlock and keeps PostMortem AI reachable", () => {
    // The user's decision: Airlock is the main product. The homepage hero
    // and the header both say so -- and the product that takes money is
    // still one click away, under an anchor the header links to.
    expect(HERO).toContain("Paid API · live");
    expect(LANDING).toContain('href="/airlock"');
    expect(LANDING).toContain('href="/#postmortem"');
    expect(LANDING).toContain('id="postmortem"');
    expect(HOME_META).toContain("Airlock and PostMortem AI");
    // The homepage must not override the site-wide identity search engines
    // have indexed -- that is a separate decision. Layout is untouched.
    const LAYOUT = readFileSync(join(__dirname, "..", "app", "layout.tsx"), "utf8");
    expect(LAYOUT).toContain('template: "%s — PostMortem AI"');
  });

  it("draws the line between what runs and what does not", () => {
    // The page used to say "not hosted yet", then "keys, metering, billing
    // not built". Both stopped being true. The split has to stay specific
    // in both directions: what is live is named, and so is what is not.
    expect(PAGE).toContain("What runs, and what doesn");
    expect(PAGE).toContain("Running now:");
    expect(PAGE).toContain("Not built yet:");
    for (const live of ["API keys", "prepaid credits", "deep scan", "append-only audit log", "per-account policy", "CSV export", "fails closed", "proxy fetch"]) {
      expect(PAGE.toLowerCase()).toContain(live.toLowerCase());
    }
    for (const missing of ["card payments", "self-hosted", "forward", "alert webhooks", "no free plan"]) {
      expect(PAGE.toLowerCase()).toContain(missing);
    }
    // Per-tenant policy shipped (migration 0034); the page must not still
    // list it as missing.
    expect(PAGE).not.toContain("per-tenant thresholds");
    expect(PAGE).toContain("Can I tune it for my own documents?");
    expect(PAGE).toContain("What is proxy mode?");
    // The FAQ must not still say it cannot be bought.
    expect(PAGE).not.toContain("Can I buy it?");
    expect(PAGE).not.toContain("Not yet. The scanner is free.");
  });

  it("says where and in what language it works, without overclaiming", () => {
    // Global API, English rules, any-language deep scan, wire from anywhere
    // and UPI in India. The rules' English limit is stated in the same
    // answer as the global claim so one cannot be quoted without the other.
    expect(PAGE).toContain("The API is global");
    expect(PAGE).toContain("match English phrasing");
    expect(PAGE).toContain("Gemini reads any language");
    expect(PAGE).toContain("SWIFT wire in USD, GBP or EUR");
    expect(PAGE).toContain("UPI in India");
    expect(LLMS_FULL).toContain("The API is global");
    expect(LLMS_FULL).toContain("rules match English phrasing");
    // No India-specific digit grouping anywhere Airlock renders a number.
    for (const source of [PAGE, PLAYGROUND, PRICING_DEFAULTS]) {
      expect(source).not.toContain('"en-IN"');
    }
  });

  it("is live where it claims to be, and documents the API where a developer looks", () => {
    // The decision counters are the client component that refreshes from
    // /stats (server-seeded), the integration section carries all three
    // languages, and /docs -- the page a developer opens first -- has the
    // API reference rather than only PostMortem AI.
    expect(PAGE).toContain("<LiveCounters initial={stats} />");
    for (const lang of ["CURL_SNIPPET", "PYTHON_SNIPPET", "TYPESCRIPT_SNIPPET"]) {
      expect(PAGE).toContain(`{${lang}}`);
    }
    const DOCS = readFileSync(join(__dirname, "..", "app", "docs", "page.tsx"), "utf8");
    expect(DOCS).toContain("Airlock API");
    for (const must of ["X-Airlock-Key", "402", "credits_remaining", "Retry-After", "X-Request-ID", "/v1/airlock/egress"]) {
      expect(DOCS).toContain(must);
    }
    const STATUS = readFileSync(join(__dirname, "..", "app", "status", "page.tsx"), "utf8");
    expect(STATUS).toContain("/v1/airlock/pricing");
    expect(STATUS).toContain("<AutoRefresh");
  });

  it("states the deep scan's terms next to the no-model promise", () => {
    // The default path makes a privacy promise (no model call). The deep
    // scan is the exception and must be described as opt-in, as sending
    // content to Gemini, as unable to lower a verdict, and as refunded when
    // unavailable -- all four, or the promise reads as broken.
    expect(PAGE).toContain("By default there is no model call");
    expect(PAGE).toContain("you choose it per");
    expect(PAGE).toContain("Gemini API");
    expect(PAGE).toContain("but never lower one");
    expect(PAGE).toContain("extra credits are");
    expect(PLAYGROUND).toContain("Gemini API");
  });

  it("answers the privacy question the page's own subject raises", () => {
    expect(PAGE).toContain("the raw content is not stored");
    expect(PAGE).toContain("SHA-256");
  });

  it("does not inherit claims from upstream that this deployment cannot back", () => {
    // Both were in the build report this page descends from, and neither is
    // true of what actually runs here: there is no CSV export endpoint, and
    // with no model call in the decision path there is no "undecided" state
    // to fail closed from -- a failure is a 5xx with no verdict.
    expect(PAGE).not.toContain("exports as CSV");
    expect(PAGE).not.toContain("it fails closed: the response is an error and the verdict is");
    // And the guarantee that WAS strengthened must say so.
    expect(PAGE).toContain("TRUNCATE");
  });

  it("is described the same way to crawlers as to humans", () => {
    // llms-full.txt and the page must not drift: an AI assistant reading
    // the text file and a person reading the page should learn the same
    // facts, which is the rule landing.tsx's header comment already sets
    // for PostMortem AI.
    expect(LLMS_FULL).toContain("30 weighted rules across 8 attack families");
    // Case-insensitive: the file says "NOT a benchmark" for emphasis and
    // the page says "not a benchmark" in prose. What must not drift is
    // that the disclaimer is present in both, not its capitalisation.
    expect(LLMS_FULL.toLowerCase()).toContain("not a benchmark");
    // The status split, in both directions. Either half going missing turns
    // the file into a different claim than the page makes.
    expect(LLMS_FULL).toContain("RUNNING NOW");
    expect(LLMS_FULL).toContain("NOT BUILT");
    expect(LLMS_FULL).not.toContain("cannot be purchased and has no price");
    expect(LLMS_FULL).toContain("X-Airlock-Key");
    expect(LLMS_FULL).toContain("402");
    expect(LLMS_FULL.toLowerCase()).toContain("no free tier");
    expect(LLMS_FULL).toContain("deep scan");
  });
});
