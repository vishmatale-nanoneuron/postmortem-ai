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
    rules: vi.fn().mockResolvedValue({
      count: 2,
      families: ["exfiltration", "instruction_override"],
      rules: [
        { id: "IO-001", family: "instruction_override", weight: 0.8, description: "Classic override phrasing." },
        { id: "EX-003", family: "exfiltration", weight: 0.75, description: "Asks for the system prompt." },
      ],
    }),
    policy: vi.fn().mockResolvedValue({
      block_threshold: 0.75,
      flag_threshold: 0.4,
      muted_rules: [],
      egress_allowlist: [],
      default: true,
      updated_at: null,
    }),
    setPolicy: vi.fn(),
    resetPolicy: vi.fn(),
    usage: vi.fn().mockResolvedValue({ days: 30, total_credits: 0, rows: [] }),
    usageCsv: vi.fn(),
  },
  airlockScan: vi.fn(),
  airlockProxyFetch: vi.fn(),
  AirlockScanError: class AirlockScanError extends Error {
    constructor(
      message: string,
      public readonly status: number,
    ) {
      super(message);
    }
  },
  billing: { updateClaim: vi.fn(), cancelClaim: vi.fn(), invoice: vi.fn() },
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

describe("PolicyEditor", () => {
  beforeEach(() => {
    vi.mocked(airlock.setPolicy).mockReset();
  });

  it("shows the defaults, and saves exactly what the form holds", async () => {
    const { PolicyEditor } = await import("../app/airlock/policy-panel");
    vi.mocked(airlock.setPolicy).mockResolvedValue({
      block_threshold: 0.6,
      flag_threshold: 0.4,
      muted_rules: ["IO-001"],
      egress_allowlist: ["api.example.com"],
      default: false,
      updated_at: 1,
    });
    render(<PolicyEditor />);
    expect(await screen.findByText("Engine defaults")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const block = screen.getByLabelText("Block at or above");
    await userEvent.clear(block);
    await userEvent.type(block, "0.6");
    await userEvent.click(await screen.findByLabelText("Mute IO-001"));
    await userEvent.type(
      screen.getByLabelText(/Egress allowlist/),
      "api.example.com",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(airlock.setPolicy).toHaveBeenCalledTimes(1));
    expect(vi.mocked(airlock.setPolicy).mock.calls[0]![0]).toEqual({
      block_threshold: 0.6,
      flag_threshold: 0.4,
      muted_rules: ["IO-001"],
      egress_allowlist: ["api.example.com"],
    });
    expect(await screen.findByText(/Saved\. Applies to the next call/)).toBeTruthy();
    // The summary now reflects the saved policy, not the defaults.
    expect(screen.getByText(/Block ≥ 0\.60 · flag ≥ 0\.40 · 1 muted · 1 allowlisted/)).toBeTruthy();
  });

  it("surfaces the API's validation message instead of swallowing it", async () => {
    const { PolicyEditor } = await import("../app/airlock/policy-panel");
    vi.mocked(airlock.setPolicy).mockRejectedValue(new Error("flag_threshold must be in (0, block_threshold]"));
    render(<PolicyEditor />);
    await screen.findByText("Engine defaults");
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Save policy" }));
    expect(await screen.findByText("flag_threshold must be in (0, block_threshold]")).toBeTruthy();
  });
});

describe("UsagePanel", () => {
  it("renders the rows the API returned, with the total", async () => {
    const { UsagePanel } = await import("../app/airlock/policy-panel");
    vi.mocked(airlock.usage).mockResolvedValueOnce({
      days: 30,
      total_credits: 14,
      rows: [
        { day: "2026-09-13", key_prefix: "alk_abcdefgh", scans: 9, deep_scans: 1, egress: 0, refunds: 0, credits: 14 },
      ],
    });
    render(<UsagePanel />);
    expect(await screen.findByText("2026-09-13")).toBeTruthy();
    expect(screen.getByText("alk_abcdefgh…")).toBeTruthy();
    expect(screen.getByText("Total, 30 days")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeTruthy();
  });
});

describe("UrlFetch", () => {
  it("shows the page text on allow and says so on a block, without ever rendering blocked content", async () => {
    const { auth } = await import("../app/auth");
    vi.mocked(auth.checkSession).mockResolvedValue({ id: "u1", email: "x@example.com" } as never);
    const { airlockProxyFetch } = await import("../app/api");
    const base = {
      score: 0,
      stage: "ingress" as const,
      reasons: [],
      matches: [],
      families: [],
      signals: {},
      url: "https://example.com/",
      final_url: "https://example.com/",
      http_status: 200,
      content_type: "text/html",
      content_bytes: 1200,
      content_sha256: "abc",
      destination_checked: false,
      hops: 0,
      truncated: false,
      fetch_ms: 80,
      latency_ms: 90,
      credits_remaining: 98,
      credits_charged: 2,
      semantic: null,
      policy: { block_threshold: 0.75, flag_threshold: 0.4, muted_rules: [], default: true },
    };
    vi.mocked(airlockProxyFetch)
      .mockResolvedValueOnce({ ...base, verdict: "allow", content: "Quarterly report\nRevenue grew 4%." })
      .mockResolvedValueOnce({ ...base, verdict: "block", score: 0.8, content: null });

    const { UrlFetch } = await import("../app/airlock/url-fetch");
    render(<UrlFetch credits={2} />);
    const button = await screen.findByRole("button", { name: "Fetch & scan it (2 credits)" });
    await userEvent.click(button);
    expect(await screen.findByText(/Revenue grew 4%/)).toBeTruthy();
    expect(screen.getByText("What your agent would receive")).toBeTruthy();

    await userEvent.click(button);
    expect(await screen.findByText(/Nothing is handed over on a block/)).toBeTruthy();
    expect(screen.queryByText(/Revenue grew 4%/)).toBeNull();
  });
});

describe("InvoiceDocument", () => {
  it("renders a proforma with the reference and no bank details, then a receipt", async () => {
    const { billing } = await import("../app/api");
    const base = {
      number: "NN-20260913-ABCDEF12",
      status: "pending",
      issued_at: Date.UTC(2026, 8, 13),
      paid_at: null,
      seller: { name: "NanoNeuron", address: null, tax_id: null },
      buyer_email: "buyer@example.com",
      line: { description: "Airlock scan credits -- 20,000 credits (2 x 10,000)", quantity: 2, unit_amount: 15, amount: 30, currency: "USD" },
      method: "wire",
      reference: "WIRE-REF-1",
      product: "airlock",
      billing_period: null,
      scan_credits: 20000,
    };
    (billing as unknown as { invoice: ReturnType<typeof vi.fn> }).invoice = vi
      .fn()
      .mockResolvedValueOnce({ ...base, kind: "proforma" })
      .mockResolvedValueOnce({ ...base, kind: "receipt", status: "approved", paid_at: Date.UTC(2026, 8, 14) });
    const { InvoiceDocument } = await import("../app/invoice/[id]/invoice-document");
    const { unmount } = render(<InvoiceDocument claimId="abc" />);
    expect(await screen.findByText("Proforma invoice")).toBeTruthy();
    expect(screen.getByText("NN-20260913-ABCDEF12")).toBeTruthy();
    expect(screen.getByText("Total due")).toBeTruthy();
    expect(screen.getAllByText("WIRE-REF-1").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Print / save as PDF" })).toBeTruthy();
    unmount();

    render(<InvoiceDocument claimId="abc" />);
    expect(await screen.findByText("Receipt")).toBeTruthy();
    expect(screen.getByText("Total paid")).toBeTruthy();
    expect(screen.getByText("Payment verified")).toBeTruthy();
  });
});

describe("failure boundaries", () => {
  it("the 404 is branded and points onward; the error boundary offers a retry and the digest", async () => {
    const { default: NotFound } = await import("../app/not-found");
    render(<NotFound />);
    expect(screen.getByText("There is nothing at this address.")).toBeTruthy();
    for (const name of [/Airlock/, /Docs/, /Pricing/, /Status/]) expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);

    const { default: ErrorBoundary } = await import("../app/error");
    const reset = vi.fn();
    const error = Object.assign(new Error("boom"), { digest: "abc123" });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary error={error} reset={reset} />);
    expect(screen.getByText("This page failed to render.")).toBeTruthy();
    expect(screen.getByText("abc123")).toBeTruthy();
    expect(screen.queryByText("boom")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});
