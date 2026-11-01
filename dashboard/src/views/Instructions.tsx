import { useEffect, useState } from "react";
import { api, type AgentInstructions } from "../api";

function Part({ title, text }: Readonly<{ title: string; text: string }>) {
  const [copied, setCopied] = useState(false);
  return (
    <section className="section" aria-label={title}>
      <div className="view-head">
        <h3>{title}</h3>
        <button
          type="button"
          className="button"
          aria-label={`Copy ${title}`}
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="instructions">{text}</pre>
    </section>
  );
}

export function Instructions() {
  const [instructions, setInstructions] = useState<AgentInstructions | null>(
    null,
  );

  useEffect(() => {
    void api.getInstructions().then(setInstructions);
  }, []);

  return (
    <section className="panel" aria-label="Instructions">
      <div className="view-head">
        <h2>The agent's instructions</h2>
        {instructions && (
          <span className="mono muted">
            Fingerprint {instructions.fingerprint}
          </span>
        )}
      </div>
      <p className="muted">
        Read only. Written from the policy wording and the claims manual.
      </p>
      {instructions && (
        <>
          <Part title="Running the queue" text={instructions.queue} />
          <Part title="Working a claim" text={instructions.claim} />
        </>
      )}
    </section>
  );
}
