import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// @testing-library/react's cleanup normally auto-registers via its
// vitest/jest integration, but that hook only fires under Jest's global
// afterEach -- under plain Vitest it must be wired explicitly, or a
// component rendered in one test is still in the DOM for the next
// (e.g. two tests each rendering PendingClaim both match "Withdraw").
afterEach(() => {
  cleanup();
});
