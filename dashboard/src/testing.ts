import { vi } from "vitest";
import type {
  Claim,
  ClaimState,
  ClaimSummary,
  Me,
  Policy,
  QueueRun,
  Run,
} from "./api";

type Handler = (body: unknown) => unknown;

export const ME: Me = {
  user_id: "USR-01",
  name: "Dana Whitfield",
  handler_id: "HND-01",
  tenant_id: "T-UNDERCOVER",
  tenant_name: "UnderCover Travel Insurance",
  roles: ["claims_handler", "senior_handler"],
  can_sign_off: true,
  can_run: true,
};

export const TRAINEE: Me = {
  ...ME,
  user_id: "USR-04",
  name: "Leon Abara",
  handler_id: "HND-04",
  roles: ["claims_handler"],
  can_sign_off: false,
};

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
    failed_attempts: 0,
    left_for_handler: false,
    ...overrides,
  };
}

export function run(overrides: Partial<Run> = {}): Run {
  return {
    run_id: "r1",
    claim_id: "CLM-1002",
    status: "succeeded",
    error: "",
    started_at: "2026-10-30T07:00:00+00:00",
    ended_at: "2026-10-30T07:00:30+00:00",
    queue_run_id: "q1",
    attempt: 1,
    failure: "",
    tokens: 1200,
    model_calls: 8,
    model: "scripted",
    seconds: 30,
    sections_read: [],
    ...overrides,
  };
}

export function queueRun(overrides: Partial<QueueRun> = {}): QueueRun {
  return {
    run_id: "q1",
    status: "running",
    cap: 5,
    limits: {
      claim_step_limit: 30,
      claim_seconds: 120,
      token_limit: 1_000_000,
      provider_failures_to_pause: 3,
    },
    model: "deepseek/deepseek-v4.1-flash",
    reasoning_effort: "low",
    fingerprint: "a1b2c3d4e5f6",
    todos: [],
    summary: "",
    stop_reason: "",
    error: "",
    tokens: 12345,
    seconds: 75,
    claims_worked: 2,
    started_at: "2026-10-30T07:00:00+00:00",
    ended_at: "",
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

/** A stubbed answer with a status other than 200 or 409. */
export class Refusal {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {}
}

export function stubApi(given: Record<string, unknown>) {
  const routes: Record<string, unknown> = {
    "GET /api/queue-runs": [],
    ...given,
  };
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
    if (result instanceof Refusal) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: result.detail }), {
          status: result.status,
        }),
      );
    }
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
