import { vi } from "vitest";
import type { Claim, ClaimState, ClaimSummary, Policy } from "./api";

type Handler = (body: unknown) => unknown;

export const STATE_ORDER: ClaimState[] = [
  "waiting",
  "in_progress",
  "waiting_for_signoff",
  "decided",
];

export function summary(
  index: number,
  overrides: Partial<ClaimSummary> = {},
): ClaimSummary {
  return {
    claim_id: `CLM-${String(1000 + index)}`,
    policy_id: `POL-${String(2000 + index)}`,
    customer_id: `CUS-${String(3000 + index)}`,
    customer: "Ana L.",
    customer_name: "Ana Lopez",
    claim_type: "baggage",
    summary: "A lost bag",
    amount_claimed: 100,
    state: STATE_ORDER[index % 4] ?? "waiting",
    state_since: new Date().toISOString(),
    decision: "",
    payout: 0,
    paid: 0,
    ...overrides,
  };
}

export function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    ...summary(2, { state: "waiting", customer_name: "Tom Becker" }),
    incident_date: "2026-06-01",
    incident_location: "Lisbon, Portugal",
    submitted_on: "2026-06-05",
    story: "My suitcase never arrived.",
    items: [{ description: "Suitcase", category: "luggage", amount: 280 }],
    documents: [
      { name: "Carrier report", type: "carrier_report", content: "Lost." },
      { name: "Receipt", type: "receipt", content: "$280.00" },
      { name: "Letter", type: "letter", content: "Sorry." },
    ],
    decisions: [],
    runs: [],
    ...overrides,
  };
}

export const POLICY: Policy = {
  policy_id: "POL-2002",
  plan: "premium",
  add_ons: ["electronics_plus"],
  travelers: ["Tom Becker"],
  trip: {
    destination: "Lisbon, Portugal",
    departs_on: "2026-05-30",
    returns_on: "2026-06-10",
    trip_cost: 2000,
  },
  limits: { name: "UnderCover Premium" },
};

export function stubApi(routes: Record<string, unknown>) {
  const calls: { key: string; body: unknown }[] = [];
  const fetch = vi.fn((path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    const body: unknown =
      typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ key, body });
    if (!(key in routes)) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: `No stub for ${key}` }), {
          status: 404,
        }),
      );
    }
    const route = routes[key];
    const result: unknown =
      typeof route === "function" ? (route as Handler)(body) : route;
    if (result instanceof Error) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: result.message }), {
          status: 409,
        }),
      );
    }
    return Promise.resolve(new Response(JSON.stringify(result)));
  });
  vi.stubGlobal("fetch", fetch);
  return calls;
}
