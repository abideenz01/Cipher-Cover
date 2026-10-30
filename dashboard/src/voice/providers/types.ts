export interface VoiceProvider {
  available: boolean;
  listen: (onText: (text: string) => void, onEnd: () => void) => () => void;
  speak: (text: string, onEnd: () => void) => void;
  cancel: () => void;
}
