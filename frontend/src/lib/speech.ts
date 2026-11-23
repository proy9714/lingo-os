// Browser voice in and out (zero setup). Neural voices and Whisper can replace these later behind the same calls.
import { useCallback, useEffect, useRef, useState } from "react";

const LOCALES: Record<string, string> = { de: "de-DE", es: "es-ES", ja: "ja-JP" };

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speak(text: string, lang: string, rate = 0.9, onEnd?: () => void): void {
  if (!canSpeak() || !text) {
    onEnd?.();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = LOCALES[lang] ?? lang;
  utterance.rate = rate;
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith(utterance.lang.slice(0, 2)));
  if (voice) utterance.voice = voice;
  if (onEnd) {
    utterance.onend = () => onEnd();
    utterance.onerror = () => onEnd();
  }
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

// ---------------------------------------------------------------- recognition

interface RecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}

interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<RecognitionResultLike> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

function recognitionClass(): (new () => RecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => RecognitionLike; webkitSpeechRecognition?: new () => RecognitionLike };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canRecognize = () => recognitionClass() !== null;

/**
 * Speech to text with the browser's recogniser. In Chrome and Edge the audio is sent to the browser maker's speech
 * service, so the UI says so next to the microphone.
 */
export function useSpeechInput(lang: string) {
  const [listening, setListening] = useState(false);
  const [finalText, setFinalText] = useState("");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognizer = useRef<RecognitionLike | null>(null);
  const finished = useRef<((text: string) => void) | null>(null);
  const collected = useRef("");

  const start = useCallback(() => {
    const Recognition = recognitionClass();
    if (!Recognition) {
      setError("This browser has no speech recognition. Chrome or Edge have one.");
      return;
    }
    recognizer.current?.abort();
    const rec = new Recognition();
    rec.lang = LOCALES[lang] ?? lang;
    rec.continuous = true;
    rec.interimResults = true;
    collected.current = "";
    setFinalText("");
    setInterim("");
    setError(null);
    rec.onresult = (event) => {
      let live = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) collected.current = `${collected.current} ${result[0].transcript}`.trim();
        else live += result[0].transcript;
      }
      setFinalText(collected.current);
      setInterim(live);
    };
    rec.onerror = (event) => {
      if (event.error !== "no-speech" && event.error !== "aborted") setError(`Speech recognition: ${event.error}`);
    };
    rec.onend = () => {
      setListening(false);
      setInterim("");
      finished.current?.(collected.current);
      finished.current = null;
    };
    recognizer.current = rec;
    rec.start();
    setListening(true);
  }, [lang]);

  /** Stops listening and resolves with everything recognised. */
  const stop = useCallback(
    () =>
      new Promise<string>((resolve) => {
        if (!recognizer.current || !listening) {
          resolve(collected.current);
          return;
        }
        finished.current = resolve;
        recognizer.current.stop();
      }),
    [listening],
  );

  useEffect(() => () => recognizer.current?.abort(), []);

  return { supported: canRecognize(), listening, text: [finalText, interim].filter(Boolean).join(" "), error, start, stop };
}

// ---------------------------------------------------------------- recording

export function canRecord(): boolean {
  return typeof window !== "undefined" && "MediaRecorder" in window && Boolean(navigator.mediaDevices?.getUserMedia);
}

export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const stream = useRef<MediaStream | null>(null);

  const start = useCallback(async () => {
    setError(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      setError("The microphone isn't available. Allow it for this page and try again.");
      return false;
    }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream.current, type ? { mimeType: type } : undefined);
    chunks.current = [];
    rec.ondataavailable = (event) => event.data.size > 0 && chunks.current.push(event.data);
    recorder.current = rec;
    startedAt.current = performance.now();
    rec.start();
    setRecording(true);
    return true;
  }, []);

  const stop = useCallback(
    () =>
      new Promise<{ blob: Blob; durationMs: number } | null>((resolve) => {
        const rec = recorder.current;
        if (!rec || rec.state === "inactive") {
          resolve(null);
          return;
        }
        rec.onstop = () => {
          stream.current?.getTracks().forEach((t) => t.stop());
          setRecording(false);
          resolve({
            blob: new Blob(chunks.current, { type: rec.mimeType || "audio/webm" }),
            durationMs: Math.round(performance.now() - startedAt.current),
          });
        };
        rec.stop();
      }),
    [],
  );

  useEffect(
    () => () => {
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  return { supported: canRecord(), recording, error, start, stop };
}
