// Regression coverage for AccountSettings (apps/web/app/workspace.tsx).
// The founder account is protected server-side (auth.py refuses to delete
// the founder), but the button being hidden client-side is also load-bearing
// UX -- it should never be visible to the founder account in the first
// place, and the non-founder path must still show it.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// AccountSettings now also renders ActivityLogPanel and its own export
// button, both of which call real api.* methods (activityLog on mount,
// exportData only on click) -- an empty mock broke as soon as
// ActivityLogPanel's useEffect ran, caught by this test suite itself,
// not assumed. Resolving to an empty array is the correct "nothing to
// show yet" case ActivityLogPanel already handles by rendering nothing.
vi.mock("../app/api", () => ({
  api: {
    activityLog: vi.fn().mockResolvedValue([]),
    exportData: vi.fn(),
  },
}));
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
  has_free_incident_available: false,
  has_used_free_incident: false,
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
