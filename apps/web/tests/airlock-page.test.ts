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

  it("reports the 18-case result as a self-authored smoke test, never as a benchmark", () => {
    expect(PAGE).toContain("18-case suite we wrote ourselves");
    expect(PAGE).toContain("That is a smoke test, not a benchmark.");
    // The words that would turn an 18-case suite into a false accuracy
    // claim. None of them belong on this page until a real benchmark runs.
    for (const forbidden of ["precision rate", "% accurate", "99.", "false-positive rate of", "accuracy of"]) {
      expect(PAGE).not.toContain(forbidden);
    }
  });

  it("sells nothing, because there is nothing to sell yet", () => {
    // No price, no checkout, and no `offers` in the structured data -- a
    // price in a rich result the page itself doesn't make would be the
    // worst version of this mistake.
    expect(PAGE).toContain("not hosted yet");
    expect(PAGE).not.toContain("$0.001");
    expect(PAGE).not.toContain('"offers"');
    expect(PAGE).not.toContain("offers:");
  });

  it("answers the privacy question the page's own subject raises", () => {
    expect(PAGE).toContain("the raw content is not stored");
    expect(PAGE).toContain("SHA-256");
  });

  it("is described the same way to crawlers as to humans", () => {
    // llms-full.txt and the page must not drift: an AI assistant reading
    // the text file and a person reading the page should learn the same
    // facts, which is the rule landing.tsx's header comment already sets
    // for PostMortem AI.
    expect(LLMS_FULL).toContain("30 weighted rules across 8 attack families");
    expect(LLMS_FULL).toContain("It is NOT hosted.");
    expect(LLMS_FULL).toContain("not a benchmark");
  });
});
