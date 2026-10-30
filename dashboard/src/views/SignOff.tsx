import { useEffect, useRef, useState } from "react";
import { api, type Handler, type SignOffItem } from "../api";
import { money, waited } from "../format";

export interface Highlight {
  claimId: string;
  handlerId: string;
}

function Row({
  item,
  handlers,
  now,
  confirmAs,
  onOpen,
  onChanged,
}: Readonly<{
  item: SignOffItem;
  handlers: Handler[];
  now: Date;
  confirmAs: string;
  onOpen: (claimId: string) => void;
  onChanged: () => void;
}>) {
  const [handlerId, setHandlerId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const handler = handlers.find((h) => h.handler_id === handlerId);
  const confirm = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (confirmAs) confirm.current?.focus();
  }, [confirmAs]);

  function act(action: Promise<unknown>) {
    setError("");
    action.then(onChanged, (e: unknown) => {
      setError(e instanceof Error ? e.message : "That did not work.");
    });
  }

  return (
    <li
      className={confirmAs ? "signoff highlight" : "signoff"}
      aria-label={`Sign-off ${item.claim_id}`}
    >
      <div>
        <button
          type="button"
          className="button mono"
          onClick={() => {
            onOpen(item.claim_id);
          }}
        >
          {item.claim_id}
        </button>{" "}
        {item.customer}
        {item.overdue && <span className="chip chip-overdue">Overdue</span>}
        <p className="accent">{item.reason}</p>
      </div>
      <div>
        <span className="payout mono">{money(item.payout)}</span>
        <span className="muted mono">
          Waited {waited(item.waiting_since, now)}
        </span>
      </div>
      <div className="signoff-actions">
        {confirmAs && (
          <button
            ref={confirm}
            type="button"
            className="button primary"
            onClick={() => {
              act(api.signOff(item.claim_id, confirmAs));
            }}
          >
            Confirm sign-off as {confirmAs}
          </button>
        )}
        <select
          aria-label={`Handler for ${item.claim_id}`}
          value={handlerId}
          onChange={(event) => {
            setHandlerId(event.target.value);
          }}
        >
          <option value="">Choose a handler</option>
          {handlers.map((h) => (
            <option key={h.handler_id} value={h.handler_id}>
              {h.handler_id} {h.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="button primary"
          disabled={!handler?.can_approve_over_limit}
          onClick={() => {
            act(api.signOff(item.claim_id, handlerId));
          }}
        >
          Sign off
        </button>
        <input
          aria-label={`Reason to send back ${item.claim_id}`}
          placeholder="Reason to send back"
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        <button
          type="button"
          className="button"
          disabled={!handler || !reason.trim()}
          onClick={() => {
            act(api.sendBack(item.claim_id, handlerId, reason.trim()));
          }}
        >
          Send back
        </button>
        {handler && !handler.can_approve_over_limit && (
          <span className="muted">
            {handler.name} cannot sign off payouts over $1,000.00.
          </span>
        )}
        {error && <span className="error">{error}</span>}
      </div>
    </li>
  );
}

export function SignOff({
  version,
  now,
  highlight,
  onOpen,
  onChanged,
}: Readonly<{
  version: string;
  now: Date;
  highlight: Highlight | null;
  onOpen: (claimId: string) => void;
  onChanged: () => void;
}>) {
  const [items, setItems] = useState<SignOffItem[]>([]);
  const [handlers, setHandlers] = useState<Handler[]>([]);

  useEffect(() => {
    void api.listHandlers().then(setHandlers);
  }, []);

  useEffect(() => {
    void api.listSignoffs().then(setItems);
  }, [version]);

  return (
    <section className="panel" aria-label="Sign-off">
      <div className="view-head">
        <h2>Waiting for sign-off</h2>
        <span className="mono muted">{items.length}</span>
      </div>
      {items.length ? (
        <ul className="signoffs">
          {items.map((item) => (
            <Row
              key={item.claim_id}
              item={item}
              handlers={handlers}
              now={now}
              confirmAs={
                item.claim_id === highlight?.claimId ? highlight.handlerId : ""
              }
              onOpen={onOpen}
              onChanged={onChanged}
            />
          ))}
        </ul>
      ) : (
        <p className="empty">
          Nothing is waiting for sign-off. Approved payouts over $1,000.00
          appear here.
        </p>
      )}
    </section>
  );
}
