// Renders the Airlock dashboard panel and the gated playground for real
// (jsdom), because tsc and next build never evaluate a client tree: an
// undefined import from a module cycle, or a hook called conditionally,
// only shows up when the component mounts. Three properties are pinned:
//
// 1. The panel mounts, shows the balance the API returned, and warns in
//    plain words when it is zero.
// 2. A freshly minted key is shown exactly once and never appears in the
//    key list -- the UI cannot leak a secret the API only returned once.
// 3. Revoking a key confirms first (window.confirm), the same discipline
//    pending-claim.test.tsx pins for withdrawing a claim.
// 4. The playground, signed out, does not render a scan button at all: it
//    says there is no free tier and points at sign-in and pricing.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../app/api", () => ({
  airlock: {
    pricing: vi.fn().mockResolvedValue({
      scans_per_pack: 10000,
      max_packs_per_claim: 10,
      credits_per_scan: 1,
      credits_per_deep_scan: 5,
      prices: [
        { currency: "INR", amount: 999, method: "upi", configured: true },
        { currency: "USD", amount: 15, method: "wire", configured: true },
      ],
    }),
    keys: vi.fn(),
    createKey: vi.fn(),
    revokeKey: vi.fn().mockResolvedValue(undefined),
    credits: vi.fn(),
    submitClaim: vi.fn(),
    myClaims: vi.fn().mockResolvedValue([]),
    emailDetails: vi.fn(),
  },
  airlockScan: vi.fn(),
  AirlockScanError: class AirlockScanError extends Error {
    constructor(
      message: string,
      public readonly status: number,
    ) {
      super(message);
    }
  },
  billing: { updateClaim: vi.fn(), cancelClaim: vi.fn() },
}));

vi.mock("../app/auth", () => ({
  auth: { checkSession: vi.fn().mockResolvedValue(null) },
}));

import { airlock } from "../app/api";
import { AirlockPanel } from "../app/airlock/airlock-panel";
import { Playground } from "../app/airlock/playground";

const KEY = {
  id: "key-1",
  label: "prod agent",
  prefix: "alk_abcdefgh",
  created_at: 1_700_000_000_000,
  last_used_at: null,
  revoked_at: null,
};

describe("AirlockPanel", () => {
  beforeEach(() => {
    vi.mocked(airlock.keys).mockResolvedValue([]);
    vi.mocked(airlock.credits).mockResolvedValue({
      balance: 0,
      purchased_total: 0,
      used_total: 0,
      used_last_30d: 0,
      statement: [],
    });
    vi.mocked(airlock.createKey).mockReset();
    vi.mocked(airlock.revokeKey).mockClear();
    vi.spyOn(window, "confirm").mockReset();
  });

  it("mounts, shows the balance, and says plainly when it is zero", async () => {
    render(<AirlockPanel isFounder={false} />);
    expect(await screen.findByRole("heading", { name: "Airlock" })).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/No credits\./)).toBeTruthy());
    expect(screen.getByText("402")).toBeTruthy();
    // The purchase form loaded its pricing.
    expect(await screen.findByText(/10,000 scans per pack/)).toBeTruthy();
  });

  it("shows a new key exactly once and never in the list", async () => {
    const user = userEvent.setup();
    vi.mocked(airlock.createKey).mockResolvedValue({ ...KEY, secret: "alk_abcdefghSECRETSECRETSECRET" });
    vi.mocked(airlock.keys).mockResolvedValueOnce([]).mockResolvedValue([KEY]);

    render(<AirlockPanel isFounder={false} />);
    await user.click(await screen.findByRole("button", { name: "Create your first key" }));

    const shown = (await screen.findByLabelText("Your new Airlock API key")) as HTMLInputElement;
    expect(shown.value).toBe("alk_abcdefghSECRETSECRETSECRET");
    expect(screen.getByText("Copy this key now. It will not be shown again.")).toBeTruthy();
    // The list row carries the prefix only.
    expect(await screen.findByText("alk_abcdefgh…")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "I have saved it" }));
    expect(screen.queryByLabelText("Your new Airlock API key")).toBeNull();
    expect(document.body.textContent).not.toContain("SECRETSECRET");
  });

  it("does not revoke a key when the confirm is dismissed", async () => {
    const user = userEvent.setup();
    vi.mocked(airlock.keys).mockResolvedValue([KEY]);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<AirlockPanel isFounder={false} />);
    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(airlock.revokeKey).not.toHaveBeenCalled();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(airlock.revokeKey).toHaveBeenCalledWith("key-1"));
  });
});

describe("Playground, signed out", () => {
  it("renders no scan button -- only the no-free-tier explanation and the two next steps", async () => {
    render(<Playground />);
    expect(await screen.findByText("The live scanner needs an account with credits.")).toBeTruthy();
    expect(screen.getByText(/there is no free tier/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in or create an account" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "See pricing" }).getAttribute("href")).toBe("#pricing");
    expect(screen.queryByRole("button", { name: /Scan it/ })).toBeNull();
  });
});
