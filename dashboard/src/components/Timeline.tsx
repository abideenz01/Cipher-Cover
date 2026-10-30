import { useEffect, useState } from "react";
import { api, type Run, type TraceEvent } from "../api";
import { time } from "../format";

const KIND_LABELS: Record<TraceEvent["kind"], string> = {
  tool_call: "Calls",
  tool_result: "Result of",
  message: "Agent",
};

function body(event: TraceEvent): string {
  if (event.kind === "tool_call") return JSON.stringify(event.detail, null, 2);
  const text = event.detail.result ?? event.detail.text;
  return typeof text === "string" ? text : "";
}

export function Timeline({
  events,
  live,
}: Readonly<{
  events: TraceEvent[];
  live: boolean;
}>) {
  return (
    <ol className="timeline" aria-label="Trace">
      {events.map((event, index) => (
        <li
          key={`${event.created_at}-${String(index)}`}
          className={live && index === events.length - 1 ? "node live" : "node"}
        >
          <span className="mono muted">{time(event.created_at)} </span>
          <strong>{KIND_LABELS[event.kind]}</strong>{" "}
          {event.kind !== "message" && (
            <span className="mono">{event.name}</span>
          )}
          {event.kind === "message" ? (
            <p className="accent">{body(event)}</p>
          ) : (
            <pre>{body(event)}</pre>
          )}
        </li>
      ))}
    </ol>
  );
}

export function Trace({ runId }: Readonly<{ runId: string }>) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const live = run === null || run.status === "running";

  useEffect(() => {
    if (!live) return;
    let active = true;
    async function load() {
      const [nextRun, nextEvents] = await Promise.all([
        api.getRun(runId),
        api.listRunEvents(runId),
      ]);
      if (!active) return;
      setRun(nextRun);
      setEvents(nextEvents);
    }
    void load();
    const timer = setInterval(() => void load(), 1000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [runId, live]);

  return (
    <>
      {run?.status === "failed" && (
        <p className="error">The run failed: {run.error}</p>
      )}
      <Timeline events={events} live={live} />
    </>
  );
}
