import { useEffect, useState } from "react";
import { api, type Claim, type Policy } from "../api";
import { label, money } from "../format";
import { Ledger } from "./Ledger";
import { DecisionChip, StateChip } from "./StateChip";
import { Trace } from "./Timeline";

const TABS = ["Overview", "Documents", "Decision", "Trace"] as const;
type Tab = (typeof TABS)[number];

function Overview({
  claim,
  policy,
}: Readonly<{ claim: Claim; policy: Policy | null }>) {
  return (
    <>
      <section className="section">
        <h3>{claim.summary}</h3>
        <p className="accent story">{claim.story}</p>
        <p className="muted">
          {claim.customer_name} · {label(claim.claim_type)} ·{" "}
          {claim.incident_location} on{" "}
          <span className="mono">{claim.incident_date}</span>
        </p>
      </section>
      <section className="section">
        <h3>Items claimed</h3>
        <table className="ledger">
          <tbody>
            {claim.items.map((item, index) => (
              <tr key={`${item.description}-${String(index)}`}>
                <td>{item.description}</td>
                <td className="muted">{label(item.category)}</td>
                <td className="amount mono">{money(item.amount)}</td>
              </tr>
            ))}
            <tr>
              <td>Total</td>
              <td />
              <td className="amount mono">{money(claim.amount_claimed)}</td>
            </tr>
          </tbody>
        </table>
      </section>
      {policy && (
        <section className="section">
          <h3>Policy</h3>
          <p>
            <span className="mono">{policy.policy_id}</span> ·{" "}
            {policy.limits.name} · {policy.trip.destination},{" "}
            <span className="mono">
              {policy.trip.departs_on} to {policy.trip.returns_on}
            </span>
          </p>
          <p className="muted">
            Travelers: {policy.travelers.join(", ")}. Add-ons:{" "}
            {policy.add_ons.length
              ? policy.add_ons.map(label).join(", ")
              : "none"}
            .
          </p>
        </section>
      )}
    </>
  );
}

function Documents({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <ul className="timeline">
      {claim.documents.map((doc) => (
        <li key={doc.name} className="doc">
          <div className="doc-head">
            <strong>{doc.name}</strong>
            <span className="chip neutral">{label(doc.type)}</span>
          </div>
          <p>{doc.content}</p>
        </li>
      ))}
    </ul>
  );
}

function DecisionTab({
  claim,
  onRun,
}: Readonly<{
  claim: Claim;
  onRun: () => void;
}>) {
  const decision = claim.decisions.at(-1);
  const runButton = claim.state === "waiting" && (
    <button type="button" className="button primary" onClick={onRun}>
      Run the agent
    </button>
  );
  if (!decision || claim.state === "waiting") {
    return (
      <section className="section">
        <p className="empty">
          No decision yet. Run the agent to decide this claim.
        </p>
        {decision && (
          <p className="muted">
            The last decision was {decision.decision} for{" "}
            {money(decision.payout)}, sent back by a handler.
          </p>
        )}
        {runButton}
      </section>
    );
  }
  return (
    <>
      <section className="section">
        <DecisionChip decision={decision.decision} />
        <span className="payout mono">{money(decision.payout)}</span>
        {claim.state === "waiting_for_signoff" && (
          <p className="muted">Waiting for a handler's sign-off.</p>
        )}
        {claim.paid > 0 && (
          <p className="muted">
            Paid <span className="mono">{money(claim.paid)}</span>.
          </p>
        )}
      </section>
      {decision.steps.length > 0 && (
        <section className="section">
          <h3>Calculation</h3>
          <Ledger steps={decision.steps} />
        </section>
      )}
      <section className="section">
        <h3>{decision.section}</h3>
        <p className="accent">{decision.reason}</p>
        <p className="muted mono">
          {decision.model} · wording {decision.wording_version}
        </p>
      </section>
    </>
  );
}

export function Drawer({
  claimId,
  version,
  onClose,
  onChanged,
}: Readonly<{
  claimId: string;
  version: string;
  onClose: () => void;
  onChanged: () => void;
}>) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      const next = await api.getClaim(claimId);
      const nextPolicy = await api.getPolicy(next.policy_id);
      if (!active) return;
      setClaim(next);
      setPolicy(nextPolicy);
    }
    void load();
    return () => {
      active = false;
    };
  }, [claimId, version]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  function run() {
    setError("");
    api.startRun(claimId).then(onChanged, (e: unknown) => {
      setError(e instanceof Error ? e.message : "The run did not start.");
    });
  }

  const latestRun = claim?.runs.at(-1);
  return (
    <>
      <div className="backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" aria-label={`Claim ${claimId}`}>
        <div className="drawer-head">
          <h2 className="mono">{claimId}</h2>
          {claim && <StateChip state={claim.state} />}
          <button type="button" className="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="tabs" role="tablist">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              className="tab"
              aria-selected={tab === name}
              onClick={() => {
                setTab(name);
              }}
            >
              {name}
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
        {claim && (
          <div role="tabpanel" aria-label={tab}>
            {tab === "Overview" && <Overview claim={claim} policy={policy} />}
            {tab === "Documents" && <Documents claim={claim} />}
            {tab === "Decision" && <DecisionTab claim={claim} onRun={run} />}
            {tab === "Trace" &&
              (latestRun ? (
                <Trace key={latestRun.run_id} runId={latestRun.run_id} />
              ) : (
                <p className="empty">
                  No runs yet. Run the agent from the Decision tab.
                </p>
              ))}
          </div>
        )}
      </aside>
    </>
  );
}
