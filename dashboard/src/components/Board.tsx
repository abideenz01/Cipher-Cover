import type { ClaimSummary } from "../api";
import { label, money, STATE_LABELS, STATES, waited } from "../format";
import { StateChip } from "./StateChip";

const EMPTY: Record<ClaimSummary["state"], string> = {
  waiting: "No claims are waiting.",
  in_progress: "Run the agent on a waiting claim to see it here.",
  waiting_for_signoff: "Approved payouts over $1,000.00 wait here.",
  decided: "Decided claims appear here.",
};

export function ClaimCard({
  claim,
  now,
  onOpen,
}: Readonly<{
  claim: ClaimSummary;
  now: Date;
  onOpen: (claimId: string) => void;
}>) {
  return (
    <button
      type="button"
      className="card"
      onClick={() => {
        onOpen(claim.claim_id);
      }}
    >
      <span className="card-top">
        <span className="mono">{claim.claim_id}</span>
        <StateChip state={claim.state} />
      </span>
      <span className="card-amount mono">{money(claim.amount_claimed)}</span>
      <span className="card-top">
        <span>{claim.customer}</span>
        <span className="muted">{label(claim.claim_type)}</span>
      </span>
      {claim.state === "waiting_for_signoff" && (
        <span className="muted mono">
          Waited {waited(claim.state_since, now)}
        </span>
      )}
    </button>
  );
}

export function Board({
  claims,
  now,
  onOpen,
}: Readonly<{
  claims: ClaimSummary[];
  now: Date;
  onOpen: (claimId: string) => void;
}>) {
  return (
    <div className="board">
      {STATES.map((state) => {
        const column = claims.filter((c) => c.state === state);
        return (
          <section
            key={state}
            className="column"
            aria-label={STATE_LABELS[state]}
          >
            <h2>
              {STATE_LABELS[state]}
              <span className="mono muted">{column.length}</span>
            </h2>
            {column.length ? (
              <ul>
                {column.map((claim) => (
                  <li key={claim.claim_id}>
                    <ClaimCard claim={claim} now={now} onOpen={onOpen} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">{EMPTY[state]}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}
