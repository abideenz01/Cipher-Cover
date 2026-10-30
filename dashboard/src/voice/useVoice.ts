import { useCallback, useEffect, useRef, useState } from "react";
import { api, type UiAction } from "../api";
import type { VoiceProvider } from "./providers/types";

export type VoiceStatus = "ready" | "listening" | "thinking" | "speaking";

export interface Caption {
  who: "you" | "assistant";
  text: string;
}

const CONSENT_KEY = "voice-consent";

export function useVoice({
  provider,
  handlerId,
  onAction,
}: {
  provider: VoiceProvider | null;
  handlerId: string;
  onAction: (action: UiAction) => void;
}) {
  const [status, setStatus] = useState<VoiceStatus>("ready");
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [asking, setAsking] = useState(false);
  const [session] = useState(() => crypto.randomUUID());
  const stopListening = useRef<(() => void) | null>(null);

  const say = useCallback((who: Caption["who"], text: string) => {
    setCaptions((current) => [...current, { who, text }]);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        setStatus("ready");
        return;
      }
      say("you", trimmed);
      setStatus("thinking");
      try {
        const result = await api.voiceTurn(session, handlerId, trimmed);
        say("assistant", result.reply);
        onAction(result.ui_action);
        setStatus("speaking");
        provider?.speak(result.speech, () => {
          setStatus((current) => (current === "speaking" ? "ready" : current));
        });
      } catch (error) {
        say(
          "assistant",
          error instanceof Error ? error.message : "That failed.",
        );
        setStatus("ready");
      }
    },
    [handlerId, onAction, provider, say, session],
  );

  const start = useCallback(() => {
    if (!provider || stopListening.current) return;
    if (localStorage.getItem(CONSENT_KEY) !== "yes") {
      setAsking(true);
      return;
    }
    provider.cancel();
    let heard = "";
    setStatus("listening");
    stopListening.current = provider.listen(
      (text) => {
        heard = text;
      },
      () => {
        stopListening.current = null;
        void send(heard);
      },
    );
  }, [provider, send]);

  const stop = useCallback(() => {
    stopListening.current?.();
  }, []);

  const cancel = useCallback(() => {
    provider?.cancel();
    setStatus((current) => (current === "speaking" ? "ready" : current));
  }, [provider]);

  const consent = useCallback(() => {
    localStorage.setItem(CONSENT_KEY, "yes");
    setAsking(false);
  }, []);

  useEffect(() => {
    if (!provider) return;
    function typing(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
    }
    function onDown(event: KeyboardEvent) {
      if (event.key === "Escape") cancel();
      if (event.key.toLowerCase() === "v" && !event.repeat && !typing(event)) {
        start();
      }
    }
    function onUp(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "v" && !typing(event)) stop();
    }
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [provider, cancel, start, stop]);

  return { status, captions, asking, start, stop, send, consent };
}
