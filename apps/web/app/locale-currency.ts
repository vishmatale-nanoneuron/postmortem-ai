// A guess at the visitor's currency and payment rail from the browser
// alone -- no geolocation request, no server round trip, nothing stored.
// It only chooses which option is selected FIRST; every option stays one
// click away, and the price shown is always the backend's own.
//
// Why it matters: the buy card used to open on INR/UPI for everyone, so a
// buyer in Berlin saw a rupee price and an Indian payment method before
// finding the one that applied to them. A wrong default is a small tax on
// every international sale; a guessed-right one costs nothing.

export type Currency = "INR" | "USD" | "GBP" | "EUR";

const EUR_ZONES = /^Europe\/(?!London|Dublin|Guernsey|Jersey|Isle_of_Man)/;

export function guessCurrency(
  timeZone: string | undefined = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : undefined,
  language: string | undefined = typeof navigator !== "undefined" ? navigator.language : undefined,
): Currency {
  const lang = (language ?? "").toLowerCase();
  const zone = timeZone ?? "";
  if (zone === "Asia/Kolkata" || zone === "Asia/Calcutta" || lang.endsWith("-in")) return "INR";
  if (zone === "Europe/London" || zone === "Europe/Dublin" || lang === "en-gb" || lang === "en-ie") return "GBP";
  if (EUR_ZONES.test(zone) || /^(de|fr|es|it|nl|pt|fi|sv|da|el|pl|cs|sk|hu|ro|bg|hr|sl|et|lv|lt)(-|$)/.test(lang)) {
    return "EUR";
  }
  return "USD";
}

// The rail follows the currency: UPI only moves rupees.
export function guessRail(currency: Currency = guessCurrency()): "upi" | "wire" {
  return currency === "INR" ? "upi" : "wire";
}
