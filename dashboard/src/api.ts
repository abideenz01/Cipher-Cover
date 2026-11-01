export type ClaimState =
  "waiting" | "in_progress" | "waiting_for_signoff" | "decided";
export type DecisionKind = "approve" | "decline" | "refer";

export interface ClaimSummary {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  customer: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  state: ClaimState;
  state_since: string;
  decision: DecisionKind | "";
  payout: number;
  paid: number;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface ClaimDocument {
  name: string;
  type: string;
  content: string;
}

export interface Step {
  label: string;
  amount: number;
}

export interface Decision {
  decision: DecisionKind;
  payout: number;
  reason: string;
  section: string;
  steps: Step[];
  model: string;
  wording_version: string;
  created_at: string;
}

export interface Run {
  run_id: string;
  claim_id: string;
  status: "running" | "succeeded" | "failed";
  error: string;
  started_at: string;
  ended_at: string;
}

export interface Claim extends ClaimSummary {
  incident_date: string;
  incident_location: string;
  submitted_on: string;
  story: string;
  items: Item[];
  documents: ClaimDocument[];
  decisions: Decision[];
  runs: Run[];
}

export interface Policy {
  policy_id: string;
  plan: string;
  add_ons: string[];
  travelers: string[];
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  limits: { name: string };
}

export interface TraceEvent {
  kind: "tool_call" | "tool_result" | "message";
  name: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface AgentInstructions {
  queue: string;
  claim: string;
  fingerprint: string;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  can_approve_over_limit: boolean;
}

export interface SignOffItem {
  claim_id: string;
  customer: string;
  payout: number;
  reason: string;
  section: string;
  waiting_since: string;
  hours_waiting: number;
  overdue: boolean;
}

export interface UiAction {
  type: "none" | "open_claim" | "focus_signoff";
  claim_id: string;
}

export interface VoiceConfig {
  enabled: boolean;
  provider: "browser" | "stub";
}

export interface VoiceResult {
  reply: string;
  speech: string;
  ui_action: UiAction;
  status: "succeeded" | "failed";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = (await response.json()) as unknown;
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : response.statusText);
  }
  return body as T;
}

function post<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  listClaims: () => request<ClaimSummary[]>("/api/claims"),
  getClaim: (claimId: string) => request<Claim>(`/api/claims/${claimId}`),
  getPolicy: (policyId: string) => request<Policy>(`/api/policies/${policyId}`),
  listHandlers: () => request<Handler[]>("/api/handlers"),
  listSignoffs: () => request<SignOffItem[]>("/api/signoffs"),
  signOff: (claimId: string, handlerId: string) =>
    post(`/api/claims/${claimId}/sign-off`, { handler_id: handlerId }),
  sendBack: (claimId: string, handlerId: string, reason: string) =>
    post(`/api/claims/${claimId}/send-back`, {
      handler_id: handlerId,
      reason,
    }),
  startRun: (claimId: string) => post<Run>(`/api/claims/${claimId}/runs`),
  startQueueRun: () => post<{ claim_ids: string[] }>("/api/runs"),
  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),
  listRunEvents: (runId: string) =>
    request<TraceEvent[]>(`/api/runs/${runId}/events`),
  getInstructions: () => request<AgentInstructions>("/api/instructions"),
  getVoiceConfig: () => request<VoiceConfig>("/api/voice/config"),
  voiceTurn: (sessionId: string, handlerId: string, text: string) =>
    post<VoiceResult>("/api/voice/turn", {
      session_id: sessionId,
      handler_id: handlerId,
      text,
    }),
};
