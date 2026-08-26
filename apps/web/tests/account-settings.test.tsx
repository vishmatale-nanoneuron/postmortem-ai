// Regression coverage for AccountSettings (apps/web/app/workspace.tsx).
// The founder account is protected server-side (auth.py refuses to delete
// the founder), but the button being hidden client-side is also load-bearing
// UX -- it should never be visible to the founder account in the first
// place, and the non-founder path must still show it.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../app/api", () => ({}));
vi.mock("../app/auth", () => ({
  auth: {
    updateAccount: vi.fn(),
    deleteAccount: vi.fn(),
  },
}));

import { AccountSettings } from "../app/workspace";
import type { AuthUser } from "../app/auth";

const baseUser: AuthUser = {
  id: "u1",
  email: "person@example.com",
  is_founder: false,
  subscription_status: "active",
  has_active_subscription: true,
};

describe("AccountSettings delete button visibility", () => {
  it("shows the delete-account control for a regular client", () => {
    render(<AccountSettings user={baseUser} onUpdated={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Delete my account" })).toBeInTheDocument();
  });

  it("hides the delete-account control for the founder account", () => {
    render(
      <AccountSettings user={{ ...baseUser, is_founder: true }} onUpdated={vi.fn()} onDeleted={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Delete my account" })).not.toBeInTheDocument();
  });

  it("disables editing the email field for the founder account", () => {
    render(
      <AccountSettings user={{ ...baseUser, is_founder: true }} onUpdated={vi.fn()} onDeleted={vi.fn()} />,
    );
    expect(screen.getByDisplayValue(baseUser.email)).toBeDisabled();
  });
});
