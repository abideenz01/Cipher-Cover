import type {
  ClaimState,
  ClaimSummary,
  DecisionKind,
  Failure,
  QueueRunStatus,
  TodoStatus,
} from "./api";

export const STATES: ClaimState[] = [
  "waiting",
  "in_progress",
  "waiting_for_signoff",
  "decided",
];

export const STATE_LABELS: Record<ClaimState, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_signoff: "Waiting for sign-off",
  decided: "Decided",
};

export const DECISION_LABELS: Record<DecisionKind, string> = {
  approve: "Approve",
  decline: "Decline",
  refer: "Refer",
};

export const TODO_LABELS: Record<TodoStatus, string> = {
  to_do: "To do",
  in_progress: "In progress",
  done: "Done",
  left_for_handler: "Left for a handler",
  not_started: "Not started",
};

export const RUN_LABELS: Record<QueueRunStatus, string> = {
  running: "Running",
  stopping: "Stopping",
  succeeded: "Finished",
  stopped: "Stopped",
  paused: "Paused",
  failed: "Failed",
};

export const STOP_REASONS: Record<string, string> = {
  cap: "It reached its cap.",
  queue_empty: "The queue is empty.",
  token_limit: "It spent its token budget.",
  stopped: "A handler stopped it.",
  provider_errors: "It paused after repeated errors from the model provider.",
  error: "It failed.",
};

export const FAILURE_LABELS: Record<Failure, string> = {
  "": "",
  provider: "model provider errors",
  step_limit: "step limit",
  time_limit: "time limit",
  error: "error",
};

export function isLive(status: QueueRunStatus): boolean {
  return status === "running" || status === "stopping";
}

export function count(n: number): string {
  return n.toLocaleString("en-US");
}

export function duration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return minutes
    ? `${String(minutes)} min ${String(seconds % 60)} s`
    : `${String(seconds)} s`;
}

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(amount: number): string {
  return dollars.format(amount);
}

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function waited(iso: string, now: Date): string {
  const minutes = Math.max(
    0,
    Math.floor((now.getTime() - new Date(iso).getTime()) / 60000),
  );
  const hours = Math.floor(minutes / 60);
  return hours
    ? `${String(hours)} h ${String(minutes % 60)} min`
    : `${String(minutes)} min`;
}

export function isToday(iso: string, now: Date): boolean {
  return new Date(iso).toDateString() === now.toDateString();
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function matches(claim: ClaimSummary, text: string): boolean {
  const query = text.trim().toLowerCase();
  return [claim.claim_id, claim.customer_name, claim.policy_id].some((field) =>
    field.toLowerCase().includes(query),
  );
}
