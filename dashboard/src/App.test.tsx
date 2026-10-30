import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { claim, POLICY, stubApi, summary } from "./testing";

const CLAIMS = Array.from({ length: 35 }, (_, i) =>
  summary(i + 1, i === 1 ? { customer_name: "Tom Becker" } : {}),
);
CLAIMS[3] = summary(4, { state: "decided", paid: 420 });
CLAIMS[7] = summary(8, { state: "decided", paid: 1500 });

beforeEach(() => {
  window.location.hash = "";
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the queue", () => {
  it("shows 35 cards in four columns, each with a labeled state chip", async () => {
    stubApi({ "GET /api/claims": CLAIMS });
    render(<App />);
    expect(await screen.findAllByRole("button", { name: /CLM-/ })).toHaveLength(
      35,
    );
    for (const name of [
      "Waiting",
      "In progress",
      "Waiting for sign-off",
      "Decided",
    ]) {
      const column = screen.getByRole("region", { name });
      const cards = within(column).getAllByRole("button");
      for (const card of cards) {
        expect(within(card).getByText(name)).toBeDefined();
      }
    }
  });

  it("shows the metrics in mono type", async () => {
    stubApi({ "GET /api/claims": CLAIMS });
    render(<App />);
    const strip = await screen.findByRole("region", { name: "Metrics" });
    const paid = await within(strip).findByText("$1,920.00");
    expect(paid.className).toContain("mono");
    expect(within(strip).getByText("Waiting").nextSibling?.textContent).toBe(
      "6",
    );
  });

  it("filters the board from the command bar", async () => {
    stubApi({ "GET /api/claims": CLAIMS });
    render(<App />);
    await screen.findAllByRole("button", { name: /CLM-/ });
    fireEvent.keyDown(window, { key: "/" });
    const search = screen.getByRole("searchbox");
    expect(document.activeElement).toBe(search);
    fireEvent.change(search, { target: { value: "1011" } });
    expect(
      screen.getAllByRole("button", { name: /CLM-/ }).map((b) => b.textContent),
    ).toEqual([expect.stringContaining("CLM-1011")]);
    fireEvent.change(search, { target: { value: "becker" } });
    expect(screen.getAllByRole("button", { name: /CLM-/ })).toHaveLength(1);
  });

  it("says when the backend is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<App />);
    expect(await screen.findByText(/backend is not responding/)).toBeDefined();
  });

  it("switches theme and remembers it", async () => {
    stubApi({ "GET /api/claims": [] });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Light mode" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("runs every waiting claim", async () => {
    const calls = stubApi({
      "GET /api/claims": [],
      "POST /api/runs": { claim_ids: [] },
    });
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Run all waiting" }),
    );
    await vi.waitFor(() => {
      expect(calls.map((c) => c.key)).toContain("POST /api/runs");
    });
  });
});

describe("the drawer", () => {
  it("opens a claim and closes on Escape", async () => {
    stubApi({
      "GET /api/claims": [claim()],
      "GET /api/claims/CLM-1002": claim(),
      "GET /api/policies/POL-2002": POLICY,
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /CLM-1002/ }));
    expect(await screen.findByText("My suitcase never arrived.")).toBeDefined();
    expect(await screen.findByText(/UnderCover Premium/)).toBeDefined();
    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));
    expect(screen.getByText("Lost.")).toBeDefined();
    fireEvent.click(screen.getByRole("tab", { name: "Decision" }));
    expect(screen.getByText(/No decision yet/)).toBeDefined();
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    expect(screen.getByText(/No runs yet/)).toBeDefined();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("starts a run and shows a refusal", async () => {
    let started = 0;
    stubApi({
      "GET /api/claims": [claim()],
      "GET /api/claims/CLM-1002": claim(),
      "GET /api/policies/POL-2002": POLICY,
      "POST /api/claims/CLM-1002/runs": () =>
        started++ ? new Error("Claim CLM-1002 is not waiting.") : {},
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /CLM-1002/ }));
    fireEvent.click(await screen.findByRole("tab", { name: "Decision" }));
    const run = screen.getByRole("button", { name: "Run the agent" });
    fireEvent.click(run);
    fireEvent.click(run);
    expect(
      await screen.findByText("Claim CLM-1002 is not waiting."),
    ).toBeDefined();
  });

  it("shows the decision with its ledger", async () => {
    const decided = claim({
      state: "waiting_for_signoff",
      paid: 0,
      decisions: [
        {
          decision: "approve",
          payout: 1500,
          reason: "The bag was lost by the airline.",
          section: "Section 5. Baggage",
          steps: [
            { label: "Suitcase", amount: 280 },
            { label: "Payout", amount: 1500 },
          ],
          model: "stub",
          wording_version: "2026.1",
          created_at: "2026-10-30T07:00:00+00:00",
        },
      ],
    });
    stubApi({
      "GET /api/claims": [decided],
      "GET /api/claims/CLM-1002": decided,
      "GET /api/policies/POL-2002": POLICY,
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /CLM-1002/ }));
    fireEvent.click(await screen.findByRole("tab", { name: "Decision" }));
    expect(screen.getByText("Approve")).toBeDefined();
    expect(screen.getAllByText("$1,500.00").length).toBeGreaterThan(1);
    expect(screen.getByText("Section 5. Baggage")).toBeDefined();
    expect(screen.getByText(/Waiting for a handler's sign-off/)).toBeDefined();
  });
});
