import { useEffect, useState } from "react";
import { api } from "../api";

export function Instructions() {
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void api.getInstructions().then((result) => {
      setText(result.text);
    });
  }, []);

  return (
    <section className="panel" aria-label="Instructions">
      <div className="view-head">
        <h2>The agent's instructions</h2>
        <button
          type="button"
          className="button"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="muted">
        Read only. The agent follows these on every claim.
      </p>
      <pre className="instructions">{text}</pre>
    </section>
  );
}
