// Regression test for a real bug found via line-by-line review: FastAPI's
// validation errors (422s) shape `detail` as an array of {type, loc, msg}
// objects, not a string -- every other error response in this app uses a
// plain string detail. `new Error(anArray)` stringifies via
// Array.prototype.toString(), which calls each object's own toString():
// a real user hitting a validation error (e.g. a weak password on
// register) would have seen the literal text "[object Object]" instead of
// the actual reason. Confirmed directly in Node before fixing, not assumed.
import { describe, expect, it } from "vitest";
import { readableDetail } from "../app/api";

describe("readableDetail", () => {
  it("passes a plain string detail through unchanged", () => {
    expect(readableDetail("Incorrect email or password")).toBe("Incorrect email or password");
  });

  it("extracts a readable message from FastAPI's array-shaped validation error", () => {
    const detail = [
      { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters" },
    ];
    expect(readableDetail(detail)).toBe("String should have at least 8 characters");
  });

  it("joins multiple validation errors into one readable message", () => {
    const detail = [
      { type: "missing", loc: ["body", "email"], msg: "Field required" },
      { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters" },
    ];
    expect(readableDetail(detail)).toBe("Field required; String should have at least 8 characters");
  });

  it("never produces the literal string '[object Object]' for an array detail", () => {
    const detail = [{ type: "missing", loc: ["body", "email"], msg: "Field required" }];
    const message = readableDetail(detail);
    expect(message).not.toContain("[object Object]");
  });

  it("returns null for a shape it can't make sense of, letting the caller fall back", () => {
    expect(readableDetail(undefined)).toBeNull();
    expect(readableDetail(null)).toBeNull();
    expect(readableDetail(42)).toBeNull();
    expect(readableDetail([])).toBeNull();
  });
});
