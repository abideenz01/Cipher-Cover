import type { VoiceProvider } from "./types";

export const STUB_TRANSCRIPT = "open claim ten twenty four";

export const stubProvider: VoiceProvider = {
  available: true,
  listen(onText, onEnd) {
    return () => {
      onText(STUB_TRANSCRIPT);
      onEnd();
    };
  },
  speak(_text, onEnd) {
    setTimeout(onEnd, 50);
  },
  cancel() {
    // The stub never speaks aloud, so there is nothing to stop.
  },
};
