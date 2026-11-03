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
  failed_attempts: number;
  left_for_handler: boolean;
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
  sections: Section[];
  run_id: string;
  steps: Step[];
  model: string;
  wording_version: string;
  created_at: string;
}

export interface Section {
  id: string;
  title: string;
}

export type Failure = "" | "provider" | "step_limit" | "time_limit" | "error";

export interface Run {
  run_id: string;
  claim_id: string;
  status: "running" | "succeeded" | "failed";
  error: string;
  started_at: string;
  ended_at: string;
  queue_run_id: string;
  attempt: number;
  failure: Failure;
  tokens: number;
  model_calls: number;
  model: string;
  seconds: number;
  sections_read: Section[];
}

export type TodoStatus =
  "to_do" | "in_progress" | "done" | "left_for_handler" | "not_started";

export interface Todo {
  claim_id: string;
  status: TodoStatus;
  note: string;
}

export type QueueRunStatus =
  "running" | "stopping" | "succeeded" | "stopped" | "paused" | "failed";

export interface QueueRun {
  run_id: string;
  status: QueueRunStatus;
  cap: number;
  limits: {
    claim_step_limit: number;
    claim_seconds: number;
    token_limit: number;
    provider_failures_to_pause: number;
  };
  model: string;
  reasoning_effort: string;
  fingerprint: string;
  todos: Todo[];
  summary: string;
  stop_reason: string;
  error: string;
  tokens: number;
  seconds: number;
  claims_worked: number;
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

export interface Me {
  user_id: string;
  name: string;
  handler_id: string;
  tenant_id: string;
  tenant_name: string;
  roles: string[];
  can_sign_off: boolean;
  can_run: boolean;
}

export interface User {
  user_id: string;
  email: string;
  name: string;
  handler_id: string;
  roles: string[];
  status: "active" | "disabled";
}

export interface NewUser {
  email: string;
  name: string;
  handler_id: string;
  roles: string[];
  password: string;
}

export interface TenantSettings {
  name: string;
  timezone: string;
  external_model_medical: boolean;
  payout_approval_limit: number;
  sign_off_sla_hours: number;
}

export const ROLES = [
  "claims_handler",
  "senior_handler",
  "siu_investigator",
  "auditor",
  "tenant_admin",
] as const;

/** Thrown when the session has ended, so the dashboard can show sign-in. */
export class SignedOut extends Error {}

let onSignedOut: () => void = () => undefined;

/** Call this when any request finds the session has ended. */
export function whenSignedOut(callback: () => void) {
  onSignedOut = callback;
}

/** The CSRF token the backend set at sign-in, sent on every write. */
export function csrfToken(): string {
  const found = document.cookie
    .split("; ")
    .find((part) => part.startsWith("cc_csrf="));
  return found ? decodeURIComponent(found.slice("cc_csrf=".length)) : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  const body = (await response.json()) as unknown;
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    const message = typeof detail === "string" ? detail : response.statusText;
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      onSignedOut();
      throw new SignedOut(message);
    }
    throw new Error(message);
  }
  return body as T;
}

function post<T>(path: string, body: unknown = {}): Promise<T> {
  return write<T>("POST", path, body);
}

function write<T>(method: string, path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export const api = {
  login: (email: string, password: string) =>
    post<Me>("/api/auth/login", { email, password }),
  logout: () => post("/api/auth/logout"),
  me: () => request<Me>("/api/auth/me"),
  listUsers: () => request<User[]>("/api/users"),
  createUser: (user: NewUser) => post<User>("/api/users", user),
  setUserRoles: (userId: string, roles: string[]) =>
    write<User>("PUT", `/api/users/${userId}/roles`, { roles }),
  disableUser: (userId: string) => post<User>(`/api/users/${userId}/disable`),
  enableUser: (userId: string) => post<User>(`/api/users/${userId}/enable`),
  getTenantSettings: () => request<TenantSettings>("/api/tenant/settings"),
  setMedical: (allowed: boolean) =>
    write<TenantSettings>("PUT", "/api/tenant/settings", {
      external_model_medical: allowed,
    }),
  listClaims: () => request<ClaimSummary[]>("/api/claims"),
  getClaim: (claimId: string) => request<Claim>(`/api/claims/${claimId}`),
  getPolicy: (policyId: string) => request<Policy>(`/api/policies/${policyId}`),
  listHandlers: () => request<Handler[]>("/api/handlers"),
  listSignoffs: () => request<SignOffItem[]>("/api/signoffs"),
  signOff: (claimId: string) => post(`/api/claims/${claimId}/sign-off`),
  sendBack: (claimId: string, reason: string) =>
    post(`/api/claims/${claimId}/send-back`, { reason }),
  startRun: (claimId: string) => post<Run>(`/api/claims/${claimId}/runs`),
  startQueueRun: (cap: number) => post<QueueRun>("/api/runs", { cap }),
  stopQueueRun: (runId: string) =>
    post<QueueRun>(`/api/queue-runs/${runId}/stop`),
  listQueueRuns: () => request<QueueRun[]>("/api/queue-runs"),
  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),
  listRunEvents: (runId: string) =>
    request<TraceEvent[]>(`/api/runs/${runId}/events`),
  getInstructions: () => request<AgentInstructions>("/api/instructions"),
  getVoiceConfig: () => request<VoiceConfig>("/api/voice/config"),
  voiceTurn: (sessionId: string, text: string) =>
    post<VoiceResult>("/api/voice/turn", { session_id: sessionId, text }),
};
