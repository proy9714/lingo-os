// Speech out with native voices, and speech in with the browser's recogniser.
//
// Speaking: the laptop makes the audio with a neural voice of the language (/api/tts, cached), because a browser
// only has the operating system's voices and a Windows laptop often has English ones only. On the phone the same
// audio comes through sync; away from the laptop, Android's own voices take over. A browser voice is used only when
// it really speaks the language: never an English voice reading German.
import { TextToSpeech } from "@capacitor-community/text-to-speech";
import { useCallback, useEffect, useRef, useState } from "react";

import { mediaUrl } from "../api/client";
import { isNativeApp } from "../sync/remote";

export const LOCALES: Record<string, string> = {
  zh: "zh-CN", hi: "hi-IN", es: "es-ES", ar: "ar-SA", fr: "fr-FR", bn: "bn-BD", pt: "pt-BR",
  ru: "ru-RU", de: "de-DE", ja: "ja-JP", ko: "ko-KR", it: "it-IT",
};

/** The regional variety each language was added with (pt-PT, fr-CA…): voices and speech recognition follow it. */
export function setSpeechLocales(locales: Record<string, string>): void {
  Object.assign(LOCALES, locales);
}

export type SpeechEngine = "neural" | "device";
let engine: SpeechEngine = "neural";
/** Set from Settings: neural voices from the laptop, or only this device's own voices. */
export function setSpeechEngine(value: SpeechEngine): void {
  engine = value;
}

type Unavailable = (lang: string, reason: string) => void;
let unavailable: Unavailable = () => undefined;
/** Called when nothing can say a text in its language (the app shows a message instead of an English accent). */
export function onSpeechUnavailable(listener: Unavailable): void {
  unavailable = listener;
}

/** Something can always try: the laptop's voices, the phone's, or a matching browser voice. */
export function canSpeak(): boolean {
  return typeof window !== "undefined";
}

let audio: HTMLAudioElement | null = null;
let finish: (() => void) | null = null;
let turn = 0;

export function speak(text: string, lang: string, rate = 0.9, onEnd?: () => void): void {
  stopSpeaking();
  const mine = ++turn;
  let ended = false;
  const done = () => {
    if (ended) return;
    ended = true;
    if (finish === done) finish = null;
    onEnd?.();
  };
  finish = done;
  if (!text.trim()) {
    done();
    return;
  }
  void (async () => {
    if (engine === "neural" && (await playNeural(text, lang, rate, mine, done))) return;
    if (mine !== turn) return;
    await speakOnDevice(text, lang, rate, mine, done);
  })();
}

export function stopSpeaking(): void {
  turn++;
  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
    audio = null;
  }
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  if (isNativeApp()) void TextToSpeech.stop().catch(() => undefined);
  finish?.();
}

/** The laptop's neural voice. False if it couldn't be reached, so the device's own voice can try. */
async function playNeural(text: string, lang: string, rate: number, mine: number, done: () => void): Promise<boolean> {
  if (!LOCALES[lang]) return false;
  const query = new URLSearchParams({ lang, text: text.slice(0, 1500), rate: rate.toFixed(2) });
  let src: string;
  try {
    src = await mediaUrl(`/api/tts?${query}`);
  } catch {
    return false;
  }
  if (mine !== turn) return true;
  const player = new Audio(src);
  audio = player;
  return new Promise<boolean>((resolve) => {
    player.onended = () => {
      done();
      resolve(true);
    };
    player.onerror = () => resolve(false); // the server said no (offline): fall back
    player.play().catch((error: unknown) => {
      // autoplay refused: nothing to fall back to, the device voice would be refused too
      if (error instanceof DOMException && error.name === "NotAllowedError") {
        done();
        resolve(true);
      } else resolve(false);
    });
  });
}

async function speakOnDevice(text: string, lang: string, rate: number, mine: number, done: () => void): Promise<void> {
  const locale = LOCALES[lang] ?? lang;
  if (isNativeApp()) {
    try {
      const { supported } = await TextToSpeech.isLanguageSupported({ lang: locale });
      if (!supported) {
        unavailable(lang, "This phone has no voice for this language. Install one in Android's text-to-speech settings.");
        done();
        return;
      }
      await TextToSpeech.speak({ text, lang: locale, rate });
    } catch {
      // stopped, or the engine failed
    }
    done();
    return;
  }
  const voice = await browserVoice(locale);
  if (mine !== turn) return;
  if (!voice) {
    unavailable(
      lang,
      engine === "device"
        ? "This device has no voice for this language. Choose native neural voices in Settings → Voices, or install one in your system's speech settings."
        : "No native voice right now: the laptop's voices need internet, and this browser has none for this language.",
    );
    done();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = voice.lang;
  utterance.voice = voice;
  utterance.rate = rate;
  utterance.onend = done;
  utterance.onerror = done;
  window.speechSynthesis.speak(utterance);
}

/** A browser voice that speaks this language (best quality first), or null. Waits for the voice list to load. */
async function browserVoice(locale: string): Promise<SpeechSynthesisVoice | null> {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  let voices = window.speechSynthesis.getVoices();
  if (!voices.length) {
    voices = await new Promise<SpeechSynthesisVoice[]>((resolve) => {
      const timer = window.setTimeout(() => resolve(window.speechSynthesis.getVoices()), 1500);
      window.speechSynthesis.addEventListener(
        "voiceschanged",
        () => {
          window.clearTimeout(timer);
          resolve(window.speechSynthesis.getVoices());
        },
        { once: true },
      );
    });
  }
  const base = locale.slice(0, 2).toLowerCase();
  const matching = voices.filter((v) => v.lang.replace("_", "-").toLowerCase().split("-")[0] === base);
  const score = (v: SpeechSynthesisVoice) =>
    (v.lang.replace("_", "-").toLowerCase() === locale.toLowerCase() ? 4 : 0) +
    (/natural|neural|online|google|premium|enhanced/i.test(v.name) ? 2 : 0);
  return matching.sort((a, b) => score(b) - score(a))[0] ?? null;
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
