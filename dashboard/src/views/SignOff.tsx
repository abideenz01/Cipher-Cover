import { useEffect, useRef, useState } from "react";
import { api, type Me, type SignOffItem } from "../api";
import { money, waited } from "../format";

export interface Highlight {
  claimId: string;
  handlerId: string;
}

function Row({
  item,
  me,
  now,
  confirmAs,
  onOpen,
  onChanged,
}: Readonly<{
  item: SignOffItem;
  me: Me;
  now: Date;
  confirmAs: string;
  onOpen: (claimId: string) => void;
  onChanged: () => void;
}>) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
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
        {confirmAs && me.can_sign_off && (
          <button
            ref={confirm}
            type="button"
            className="button primary"
            onClick={() => {
              act(api.signOff(item.claim_id));
            }}
          >
            Confirm sign-off as {confirmAs}
          </button>
        )}
        <button
          type="button"
          className="button primary"
          disabled={!me.can_sign_off}
          onClick={() => {
            act(api.signOff(item.claim_id));
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
          disabled={!me.handler_id || !reason.trim()}
          onClick={() => {
            act(api.sendBack(item.claim_id, reason.trim()));
          }}
        >
          Send back
        </button>
        {!me.can_sign_off && (
          <span className="muted">
            {me.name} cannot sign off payouts over $1,000.00.
          </span>
        )}
        {error && <span className="error">{error}</span>}
      </div>
    </li>
  );
}

export function SignOff({
  me,
  version,
  now,
  highlight,
  onOpen,
  onChanged,
}: Readonly<{
  me: Me;
  version: string;
  now: Date;
  highlight: Highlight | null;
  onOpen: (claimId: string) => void;
  onChanged: () => void;
}>) {
  const [items, setItems] = useState<SignOffItem[]>([]);

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
              me={me}
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
