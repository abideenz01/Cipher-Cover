import { useState } from "react";
import type { Caption } from "./useVoice";

function CaptionText({
  text,
  onOpen,
}: Readonly<{ text: string; onOpen: (claimId: string) => void }>) {
  const parts = text.split(/(CLM-\d{4})/);
  return (
    <>
      {parts.map((part, index) =>
        /^CLM-\d{4}$/.test(part) ? (
          <button
            key={`${part}-${String(index)}`}
            type="button"
            className="chip neutral mono"
            onClick={() => {
              onOpen(part);
            }}
          >
            {part}
          </button>
        ) : (
          <span key={`${part}-${String(index)}`}>{part}</span>
        ),
      )}
    </>
  );
}

export function CaptionsPanel({
  captions,
  speaker,
  onSend,
  onOpen,
}: Readonly<{
  captions: Caption[];
  speaker: string;
  onSend: (text: string) => void;
  onOpen: (claimId: string) => void;
}>) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(true);
  return (
    <section className="captions" aria-label="Voice assistant">
      <div className="captions-head">
        <span className="muted">Speaking as {speaker}</span>
        <button
          type="button"
          className="button"
          onClick={() => {
            setOpen(!open);
          }}
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <>
          <ol className="caption-list" aria-label="Captions">
            {captions.map((caption, index) => (
              <li
                key={`${caption.who}-${String(index)}`}
                className={`caption caption-${caption.who}`}
              >
                <CaptionText text={caption.text} onOpen={onOpen} />
              </li>
            ))}
          </ol>
          <form
            className="type-instead"
            onSubmit={(event) => {
              event.preventDefault();
              onSend(text);
              setText("");
            }}
          >
            <input
              aria-label="Type instead"
              placeholder="Type instead"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
            <button type="submit" className="button primary">
              Send
            </button>
          </form>
        </>
      )}
    </section>
  );
}

export function ConsentNotice({
  onContinue,
}: Readonly<{ onContinue: () => void }>) {
  return (
    <div className="consent" role="dialog" aria-label="Voice consent">
      <p>
        Voice uses your browser's speech recognition and speech. In Chrome and
        Edge the browser vendor processes the audio. Cipher Cover never stores
        audio, and captions show everything said.
      </p>
      <button type="button" className="button primary" onClick={onContinue}>
        Continue
      </button>
    </div>
  );
}
