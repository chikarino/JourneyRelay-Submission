"use client";
// Web Speech API wrappers. STT: dictation into the current short chat reply.
// TTS: read the arrangement summary aloud. Browsers without support degrade
// gracefully (buttons are hidden by the caller).

export type SpeechLang = "zh-HK" | "zh-CN" | "en-US" | "en-GB";

export function speechSupported(): boolean {
  return typeof window !== "undefined"
    && Boolean(("SpeechRecognition" in window) || ("webkitSpeechRecognition" in window));
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

type RecognitionCtor = new () => {
  lang: string; continuous: boolean; interimResults: boolean;
  start(): void; stop(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

export function listenOnce(
  lang: SpeechLang,
  onText: (text: string, isFinal: boolean) => void,
  onEnd: (err: string | null) => void,
): () => void {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) {
    onEnd("unsupported");
    return () => undefined;
  }
  const rec = new Ctor();
  rec.lang = lang;
  rec.continuous = true;
  rec.interimResults = true;
  rec.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      onText(result[0].transcript, result.isFinal);
    }
  };
  rec.onerror = (event) => onEnd(event.error);
  rec.onend = () => onEnd(null);
  rec.start();
  return () => rec.stop();
}

export function speak(text: string, lang: "zh" | "en"): void {
  if (!ttsSupported()) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang === "zh" ? "zh-HK" : "en-US";
  const voice = synth.getVoices().find((v) => v.lang.replace("_", "-").startsWith(utterance.lang));
  if (voice) utterance.voice = voice;
  utterance.rate = 1;
  synth.speak(utterance);
}
