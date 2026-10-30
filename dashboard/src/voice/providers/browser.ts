import type { VoiceProvider } from "./types";

interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }>>;
      }) => void)
    | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type RecognitionClass = new () => Recognition;

export function browserProvider(): VoiceProvider {
  const speechWindow = window as unknown as {
    SpeechRecognition?: RecognitionClass;
    webkitSpeechRecognition?: RecognitionClass;
  };
  const Recognition =
    speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
  return {
    available: Recognition !== undefined,
    listen(onText, onEnd) {
      if (!Recognition) {
        onEnd();
        return () => undefined;
      }
      const recognition = new Recognition();
      recognition.lang = "en-US";
      recognition.interimResults = false;
      recognition.continuous = false;
      recognition.onresult = (event) => {
        onText(
          Array.from(event.results)
            .map((result) => result[0].transcript)
            .join(" "),
        );
      };
      recognition.onend = onEnd;
      recognition.start();
      return () => {
        recognition.stop();
      };
    },
    speak(text, onEnd) {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-US";
      utterance.onend = onEnd;
      utterance.onerror = onEnd;
      speechSynthesis.speak(utterance);
    },
    cancel() {
      speechSynthesis.cancel();
    },
  };
}
