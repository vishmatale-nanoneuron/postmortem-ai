// Regression coverage for the withdraw-a-claim flow added this session
// (apps/web/app/workspace.tsx PendingClaim). The real risk here isn't the
// UI rendering -- it's that a destructive action (billing.cancelClaim,
// which server-side soft-cancels a payment claim) must never fire without
// the user confirming first via window.confirm.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../app/api", () => ({
  billing: {
    updateClaim: vi.fn(),
    cancelClaim: vi.fn().mockResolvedValue(undefined),
  },
}));

import { billing } from "../app/api";
import { PendingClaim } from "../app/workspace";

const claim = {
  id: "claim-1",
  method: "upi",
  currency: "INR",
  amount: 999,
  reference: "TXN123",
  status: "pending",
  created_at: Date.now(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PendingClaim withdraw", () => {
  it("does not cancel the claim when the user declines the confirm dialog", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<PendingClaim claim={claim} onChanged={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(window.confirm).toHaveBeenCalledWith(
      `Withdraw reference "${claim.reference}"? You can submit a new one afterward.`,
    );
    expect(billing.cancelClaim).not.toHaveBeenCalled();
  });

  it("cancels the claim only after the user confirms", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(<PendingClaim claim={claim} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(billing.cancelClaim).toHaveBeenCalledWith(claim.id);
    expect(onChanged).toHaveBeenCalled();
  });
});
