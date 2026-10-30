import { useRef } from "react";
import type { VoiceStatus } from "./useVoice";

const WORDS: Record<VoiceStatus, string> = {
  ready: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

const HOLD_MS = 300;

export function MicButton({
  status,
  onPress,
  onRelease,
}: Readonly<{
  status: VoiceStatus;
  onPress: () => void;
  onRelease: () => void;
}>) {
  const pressedAt = useRef(0);
  return (
    <div className="mic-wrap">
      <button
        type="button"
        className={`mic mic-${status}`}
        aria-label="Hold to talk, or tap to talk hands-free"
        onPointerDown={() => {
          pressedAt.current = Date.now();
          onPress();
        }}
        onPointerUp={() => {
          if (Date.now() - pressedAt.current >= HOLD_MS) onRelease();
        }}
      >
        {status === "thinking" ? (
          <span aria-hidden="true">•••</span>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v4" />
          </svg>
        )}
        {status === "speaking" && <span className="level" aria-hidden="true" />}
      </button>
      <span className="mic-word" aria-live="polite">
        {WORDS[status]}
      </span>
    </div>
  );
}
