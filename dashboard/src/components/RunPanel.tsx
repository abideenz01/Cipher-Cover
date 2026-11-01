import type { QueueRun, Todo } from "../api";
import {
  count,
  duration,
  isLive,
  RUN_LABELS,
  STOP_REASONS,
  time,
  TODO_LABELS,
} from "../format";

function TodoRow({ todo }: Readonly<{ todo: Todo }>) {
  return (
    <li className="todo">
      <span className="mono">{todo.claim_id}</span>
      <span className="muted todo-note">{todo.note}</span>
      <span className={`chip chip-${todo.status}`}>
        {TODO_LABELS[todo.status]}
      </span>
    </li>
  );
}

export function RunStatusChip({ run }: Readonly<{ run: QueueRun }>) {
  return (
    <span className={`chip chip-run-${run.status}`}>
      {RUN_LABELS[run.status]}
    </span>
  );
}

function Usage({ run }: Readonly<{ run: QueueRun }>) {
  return (
    <p className="muted mono run-usage">
      {count(run.tokens)} of {count(run.limits.token_limit)} tokens ·{" "}
      {duration(run.seconds)} · {run.claims_worked} claims ·{" "}
      {run.cap ? `cap ${String(run.cap)}` : "no cap"} · {run.model}
      {run.reasoning_effort && ` (${run.reasoning_effort})`} · up to{" "}
      {run.limits.claim_step_limit} steps and {run.limits.claim_seconds} s a
      claim
    </p>
  );
}

export function RunPanel({
  run,
  history,
  onSelect,
}: Readonly<{
  run: QueueRun | undefined;
  history: QueueRun[];
  onSelect: (runId: string) => void;
}>) {
  if (!run) {
    return (
      <section className="panel run-panel" aria-label="Run">
        <p className="empty">
          No runs yet. Choose how many claims to work and press Run.
        </p>
      </section>
    );
  }
  return (
    <section className="panel run-panel" aria-label="Run">
      <div className="view-head">
        <h2>
          Run <span className="mono muted">{time(run.started_at)}</span>
        </h2>
        <RunStatusChip run={run} />
      </div>
      {run.todos.length ? (
        <ol className="todos" aria-label="To-do list">
          {run.todos.map((todo) => (
            <TodoRow key={todo.claim_id} todo={todo} />
          ))}
        </ol>
      ) : (
        <p className="empty">
          {isLive(run.status)
            ? "The agent is planning its to-do list."
            : "This run made no to-do list."}
        </p>
      )}
      <Usage run={run} />
      {run.summary && <p className="accent run-summary">{run.summary}</p>}
      {!isLive(run.status) && run.stop_reason && (
        <p className="muted">
          {STOP_REASONS[run.stop_reason] ?? run.stop_reason}
          {run.error && ` ${run.error}`}
        </p>
      )}
      {history.length > 1 && (
        <details className="run-history">
          <summary>Run history</summary>
          <ul>
            {history.map((past) => (
              <li key={past.run_id}>
                <button
                  type="button"
                  className="history-row"
                  aria-current={past.run_id === run.run_id}
                  onClick={() => {
                    onSelect(past.run_id);
                  }}
                >
                  <span className="mono">{time(past.started_at)}</span>
                  <RunStatusChip run={past} />
                  <span className="mono muted">
                    {past.claims_worked} claims · {count(past.tokens)} tokens
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
