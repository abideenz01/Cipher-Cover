import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { claim, POLICY, queueRun, run, stubApi, summary } from "./testing";

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

  it("starts a run capped at five, or at all waiting claims", async () => {
    const calls = stubApi({
      "GET /api/claims": [],
      "POST /api/runs": queueRun({ status: "succeeded" }),
    });
    render(<App />);
    expect(await screen.findByText(/No runs yet/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "All" }));
    const field = screen.getByRole("spinbutton", { name: "Claims" });
    expect(field.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await vi.waitFor(() => {
      expect(
        calls.filter((c) => c.key === "POST /api/runs").map((c) => c.body),
      ).toEqual([{ cap: 5 }, { cap: 0 }]);
    });
  });

  it("changes the cap and shows a refusal", async () => {
    const calls = stubApi({
      "GET /api/claims": [],
      "POST /api/runs": new Error("Queue run q1 is still running."),
    });
    render(<App />);
    const field = await screen.findByRole("spinbutton", { name: "Claims" });
    fireEvent.change(field, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(
      await screen.findByText("Queue run q1 is still running."),
    ).toBeDefined();
    expect(calls.find((c) => c.key === "POST /api/runs")?.body).toEqual({
      cap: 2,
    });
  });

  it("shows the live run's to-do list and a Stop button", async () => {
    const live = queueRun({
      todos: [
        { claim_id: "CLM-1001", status: "done", note: "approve, $420.00" },
        { claim_id: "CLM-1002", status: "in_progress", note: "" },
        { claim_id: "CLM-1003", status: "to_do", note: "" },
        { claim_id: "CLM-1004", status: "left_for_handler", note: "" },
        { claim_id: "CLM-1005", status: "not_started", note: "" },
      ],
    });
    const calls = stubApi({
      "GET /api/claims": [],
      "GET /api/queue-runs": [live],
      "POST /api/queue-runs/q1/stop": queueRun({ status: "stopping" }),
    });
    render(<App />);
    const list = await screen.findByRole("list", { name: "To-do list" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.lastChild?.textContent),
    ).toEqual([
      "Done",
      "In progress",
      "To do",
      "Left for a handler",
      "Not started",
    ]);
    expect(screen.getByText(/12,345 of 1,000,000 tokens/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await vi.waitFor(() => {
      expect(calls.map((c) => c.key)).toContain("POST /api/queue-runs/q1/stop");
    });
  });

  it("opens a past run from the history", async () => {
    const latest = queueRun({
      run_id: "q2",
      status: "succeeded",
      summary: "Decided 5 claims.",
      stop_reason: "cap",
      started_at: "2026-10-30T09:00:00+00:00",
    });
    const older = queueRun({
      run_id: "q1",
      status: "stopped",
      summary: "Stopped after 1 claim.",
      stop_reason: "stopped",
      reasoning_effort: "",
      cap: 0,
    });
    stubApi({ "GET /api/claims": [], "GET /api/queue-runs": [latest, older] });
    render(<App />);
    expect(await screen.findByText("Decided 5 claims.")).toBeDefined();
    expect(screen.getByText("It reached its cap.")).toBeDefined();
    expect(screen.getByRole("button", { name: "Run" })).toBeDefined();
    fireEvent.click(screen.getByText("Run history"));
    const rows = screen.getAllByRole("button", { name: /Stopped/ });
    fireEvent.click(rows[0]);
    expect(await screen.findByText("Stopped after 1 claim.")).toBeDefined();
    expect(screen.getByText("A handler stopped it.")).toBeDefined();
    expect(screen.getByText(/no cap/)).toBeDefined();
  });

  it("marks a claim left for a handler", async () => {
    stubApi({
      "GET /api/claims": [
        summary(1, {
          state: "waiting",
          failed_attempts: 2,
          left_for_handler: true,
        }),
      ],
    });
    render(<App />);
    const card = await screen.findByRole("button", { name: /CLM-1001/ });
    expect(within(card).getByText("Left for a handler")).toBeDefined();
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
    expect(screen.getByText(/No attempts yet/)).toBeDefined();
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
          sections: [
            { id: "wording-5", title: "Section 5. Baggage" },
            { id: "manual-7", title: "Manual 7. Interpretation notes" },
          ],
          run_id: "r1",
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
    const relied = screen.getByRole("list", { name: "Sections relied on" });
    expect(
      within(relied)
        .getAllByRole("listitem")
        .map((i) => i.textContent),
    ).toEqual([
      "wording-5 Section 5. Baggage",
      "manual-7 Manual 7. Interpretation notes",
    ]);
    expect(screen.getByText(/Waiting for a handler's sign-off/)).toBeDefined();
  });

  it("groups the trace by attempt with the sections each read", async () => {
    const tried = claim({
      runs: [
        run({ run_id: "r1", status: "failed", failure: "provider" }),
        run({
          run_id: "r2",
          attempt: 2,
          sections_read: [
            { id: "wording-3", title: "Section 3. Trip Delay" },
            { id: "manual-10", title: "Manual 10. Meals without receipts" },
          ],
        }),
      ],
    });
    stubApi({
      "GET /api/claims": [tried],
      "GET /api/claims/CLM-1002": tried,
      "GET /api/policies/POL-2002": POLICY,
      "GET /api/runs/r1": run({ status: "failed", error: "Bad gateway." }),
      "GET /api/runs/r1/events": [],
      "GET /api/runs/r2": run({ run_id: "r2" }),
      "GET /api/runs/r2/events": [],
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /CLM-1002/ }));
    fireEvent.click(await screen.findByRole("tab", { name: "Trace" }));
    expect(
      screen.getByText("Attempt 1 · failed (model provider errors)"),
    ).toBeDefined();
    const second = screen.getByRole("region", { name: "Attempt 2" });
    expect(within(second).getByText("Attempt 2 · succeeded")).toBeDefined();
    const read = within(second).getByRole("list", { name: "Sections read" });
    expect(
      within(read)
        .getAllByRole("listitem")
        .map((i) => i.textContent),
    ).toEqual([
      "wording-3 Section 3. Trip Delay",
      "manual-10 Manual 10. Meals without receipts",
    ]);
    expect(
      screen.getAllByText(/1,200 tokens · 8 model calls · 30 s/),
    ).toHaveLength(2);
    expect(await screen.findByText(/Bad gateway/)).toBeDefined();
  });
});
