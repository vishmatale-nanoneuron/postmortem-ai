import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The /airlock page makes quantitative claims about a product whose code
// lives in a different repository, and it makes them about a product that
// cannot yet be bought. Both of those are ways a marketing page goes wrong
// quietly, so both are pinned here.
//
// The numbers below were produced by running Airlock's own code
// (backend/app/engine/rules.py -- 30 rules, 8 families;
// engine/detector.py -- block 0.75 / flag 0.40; engine/egress.py -- 11
// credential and 7 PII patterns; tests/test_detector.py -- 11 attacks
// blocked, 7 benign documents at 0.00). If Airlock's rule set grows, this
// test is what fails, and the page must be re-checked against the engine
// rather than left quoting a stale count.
const PAGE = readFileSync(join(__dirname, "..", "app", "airlock", "page.tsx"), "utf8");
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

  it("sells nothing, because there is still nothing to buy", () => {
    // The scanner is live now, but the commercial product around it -- keys,
    // metering, billing -- is not. No price, no checkout, and no `offers` in
    // the structured data: a price in a rich result the page itself doesn't
    // make would be the worst version of this mistake.
    expect(PAGE).not.toContain("$0.001");
    expect(PAGE).not.toContain('"offers"');
    expect(PAGE).not.toContain("offers:");
  });

  it("draws the line between what runs and what does not", () => {
    // The page used to say "not hosted yet", which stopped being true when
    // /v1/airlock/scan went live in this repo's backend. The replacement
    // claim has to be equally specific in the other direction, or the page
    // quietly starts implying the commercial product exists.
    expect(PAGE).toContain("What runs, and what doesn");
    expect(PAGE).toContain("Not built yet:");
    for (const missing of ["API keys", "metering", "billing"]) {
      expect(PAGE).toContain(missing);
    }
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
    expect(LLMS_FULL).toContain("cannot be purchased and has no price");
  });
});
