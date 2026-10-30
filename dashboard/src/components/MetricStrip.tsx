import type { ClaimSummary } from "../api";
import { isToday, money } from "../format";

export function MetricStrip({
  claims,
  now,
}: Readonly<{
  claims: ClaimSummary[];
  now: Date;
}>) {
  const count = (state: ClaimSummary["state"]) =>
    claims.filter((c) => c.state === state).length;
  const decidedToday = claims.filter(
    (c) => c.state === "decided" && isToday(c.state_since, now),
  ).length;
  const paid = claims.reduce((total, c) => total + c.paid, 0);
  const metrics = [
    { label: "Waiting", value: String(count("waiting")) },
    { label: "In progress", value: String(count("in_progress")) },
    {
      label: "Waiting for sign-off",
      value: String(count("waiting_for_signoff")),
    },
    { label: "Decided today", value: String(decidedToday) },
    { label: "Paid", value: money(paid) },
  ];
  return (
    <section className="metric-strip" aria-label="Metrics">
      {metrics.map((m) => (
        <div key={m.label} className="metric">
          <span className="muted">{m.label}</span>
          <span className="metric-value mono">{m.value}</span>
        </div>
      ))}
    </section>
  );
}
