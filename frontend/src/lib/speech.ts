// Pronunciation through the browser's built-in voices (zero setup). Better voices arrive with the TTS layer.

const LOCALES: Record<string, string> = { de: "de-DE", es: "es-ES", ja: "ja-JP" };

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speak(text: string, lang: string, rate = 0.9): void {
  if (!canSpeak() || !text) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = LOCALES[lang] ?? lang;
  utterance.rate = rate;
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith(utterance.lang.slice(0, 2)));
  if (voice) utterance.voice = voice;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}
