import type { ClaimState, DecisionKind } from "../api";
import { DECISION_LABELS, STATE_LABELS } from "../format";

export function StateChip({ state }: Readonly<{ state: ClaimState }>) {
  return <span className={`chip chip-${state}`}>{STATE_LABELS[state]}</span>;
}

export function DecisionChip({
  decision,
}: Readonly<{ decision: DecisionKind }>) {
  return (
    <span className={`chip chip-${decision}`}>{DECISION_LABELS[decision]}</span>
  );
}
