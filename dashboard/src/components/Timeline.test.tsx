import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { TraceEvent } from "../api";
import { stubApi } from "../testing";
import { Timeline, Trace } from "./Timeline";

const EVENTS: TraceEvent[] = [
  {
    kind: "tool_call",
    name: "get_claim",
    detail: { claim_id: "CLM-1001" },
    created_at: "2026-10-30T07:00:00+00:00",
  },
  {
    kind: "tool_result",
    name: "get_claim",
    detail: { result: '{"claim_id": "CLM-1001"}' },
    created_at: "2026-10-30T07:00:01+00:00",
  },
  {
    kind: "message",
    name: "agent",
    detail: { text: "Approved." },
    created_at: "2026-10-30T07:00:02+00:00",
  },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("pulses the last node only while the run is live", () => {
  const { rerender } = render(<Timeline events={EVENTS} live />);
  const nodes = screen.getAllByRole("listitem");
  expect(nodes).toHaveLength(3);
  expect(nodes.map((n) => n.className)).toEqual(["node", "node", "node live"]);
  rerender(<Timeline events={EVENTS} live={false} />);
  expect(screen.getAllByRole("listitem").map((n) => n.className)).toEqual([
    "node",
    "node",
    "node",
  ]);
  expect(screen.getByText("Approved.")).toBeDefined();
});

it("loads a finished run's trace and shows a failure", async () => {
  stubApi({
    "GET /api/runs/r1": {
      status: "failed",
      error: "The model is unavailable.",
    },
    "GET /api/runs/r1/events": EVENTS,
  });
  render(<Trace runId="r1" />);
  expect(await screen.findByText(/The model is unavailable/)).toBeDefined();
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
});
