// The visitor's currency is guessed from the browser alone and only picks
// what is selected first. These pin the mapping so a change is deliberate:
// India -> INR/UPI, UK & Ireland -> GBP, the euro zone -> EUR, everyone
// else -> USD, and a wire for anything that is not rupees.
import { describe, expect, it } from "vitest";
import { guessCurrency, guessRail } from "../app/locale-currency";

describe("guessCurrency", () => {
  it("maps the obvious cases", () => {
    expect(guessCurrency("Asia/Kolkata", "en-US")).toBe("INR");
    expect(guessCurrency("America/New_York", "en-IN")).toBe("INR");
    expect(guessCurrency("Europe/London", "en-US")).toBe("GBP");
    expect(guessCurrency("Europe/Dublin", "en")).toBe("GBP");
    expect(guessCurrency("Europe/Berlin", "en-US")).toBe("EUR");
    expect(guessCurrency("Europe/Paris", "fr-FR")).toBe("EUR");
    expect(guessCurrency("America/Sao_Paulo", "de-DE")).toBe("EUR");
    expect(guessCurrency("America/New_York", "en-US")).toBe("USD");
    expect(guessCurrency("Asia/Singapore", "en-SG")).toBe("USD");
    expect(guessCurrency("Australia/Sydney", "en-AU")).toBe("USD");
    expect(guessCurrency("", "")).toBe("USD");
  });

  it("chooses the rail from the currency", () => {
    expect(guessRail("INR")).toBe("upi");
    for (const c of ["USD", "GBP", "EUR"] as const) expect(guessRail(c)).toBe("wire");
  });
});
