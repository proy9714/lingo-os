// The phone side of sync: talk to the laptop's Wi-Fi listener with encrypted requests.
// On the laptop itself none of this is used (no remote config is stored there).
import { create } from "zustand";

import { importKey, openEnvelope, seal, type Envelope } from "./crypto";

export interface RemoteConfig {
  hubs: string[];
  device: string;
  token: string;
  key: string;
  hubName: string;
  active?: string;
}

interface PairingCode {
  v: number;
  hub: string[];
  device: string;
  token: string;
  key: string;
  name: string;
}

const CONFIG = "lingo.remote";

export class OfflineError extends Error {
  constructor() {
    super("You're offline: this needs your Lingo OS laptop or server in reach.");
  }
}

export class HubError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Connection state shown in the app bar and the offline banner. */
interface SyncState {
  /** null = not known yet; false = the laptop or server can't be reached right now */
  online: boolean | null;
  /** a reachability check is running */
  checking: boolean;
  pending: number;
  lastSync: string | null;
  set: (patch: Partial<Omit<SyncState, "set">>) => void;
}

export const useSyncState = create<SyncState>((set) => ({
  online: null,
  checking: false,
  pending: 0,
  lastSync: null,
  set: (patch) => set(patch),
}));

export function isNativeApp(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

export function remoteConfig(): RemoteConfig | null {
  try {
    const raw = window.localStorage.getItem(CONFIG);
    return raw ? (JSON.parse(raw) as RemoteConfig) : null;
  } catch {
    return null;
  }
}

function saveConfig(cfg: RemoteConfig | null) {
  try {
    if (cfg) window.localStorage.setItem(CONFIG, JSON.stringify(cfg));
    else window.localStorage.removeItem(CONFIG);
  } catch {
    // storage unavailable: pairing won't persist
  }
  cachedKey = null;
}

/**
 * Answers saved from a laptop (the page cache and the offline copies of settings and languages) belong to that laptop:
 * pairing with another one, or disconnecting, starts clean so its languages never show up again.
 */
export function forgetLaptopAnswers(): void {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key === "lingo.query-cache" || key.startsWith("lingo.cache.")) window.localStorage.removeItem(key);
    }
  } catch {
    // storage unavailable: nothing saved to forget
  }
}

export const disconnect = () => {
  saveConfig(null);
  forgetLaptopAnswers();
};

let cachedKey: { raw: string; key: CryptoKey } | null = null;
async function keyFor(cfg: RemoteConfig): Promise<CryptoKey> {
  if (!cachedKey || cachedKey.raw !== cfg.key) cachedKey = { raw: cfg.key, key: await importKey(cfg.key) };
  return cachedKey.key;
}

/** Rejects after `ms` even when the platform ignores AbortSignal (the Android app's native HTTP may). */
export function withTimeout<T>(promise: Promise<T>, ms: number, onTimeout?: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      onTimeout?.();
      reject(new Error("timed out"));
    }, ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

async function postTo(hub: string, path: string, body: unknown, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const request = fetch(`${hub}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  });
  return withTimeout(request, timeoutMs, () => controller.abort());
}

// ---------------------------------------------------------------- reachability
//
// Away from home a saved Wi-Fi address doesn't refuse the connection, it just never answers. Trying the addresses one
// after another with a long timeout each made every request wait minutes before falling back to what's saved offline.
// Instead every address is asked at once with a short "hello", and the first that answers is used (and remembered for
// a minute). When none answers, the app is offline for a while: requests fail at once, so offline answers show at
// once, while a check runs in the background every half minute, when the device gets a connection, and when the app
// comes back to the foreground.

const PROBE_MS = 3_000; // a reachable laptop or server answers "hello" well within this
const GOOD_FOR_MS = 60_000; // an address that answered is used without asking again for this long
const OFFLINE_FOR_MS = 20_000; // after nothing answered, requests fail at once for this long
const RECHECK_MS = 30_000;

let goodHub: { hub: string; until: number } | null = null;
let offlineUntil = 0;
let resolving: Promise<string | null> | null = null;
let recheckTimer: number | null = null;
const listeners = new Set<(online: boolean) => void>();

/** Called with true when the laptop or server comes back in reach, and false when it's lost. */
export function onReachability(listener: (online: boolean) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The computer's own server answered (true) or couldn't be reached (false): same state and listeners as the phone. */
export function reportReachable(online: boolean) {
  setOnline(online);
}

function setOnline(online: boolean) {
  const before = useSyncState.getState().online;
  useSyncState.getState().set({ online });
  if (before !== online) for (const listener of listeners) listener(online);
}

function markOffline() {
  goodHub = null;
  offlineUntil = Date.now() + OFFLINE_FOR_MS;
  setOnline(false);
  if (recheckTimer === null) recheckTimer = window.setInterval(() => void checkReachability(), RECHECK_MS);
}

function markOnline(hub: string) {
  goodHub = { hub, until: Date.now() + GOOD_FOR_MS };
  offlineUntil = 0;
  if (recheckTimer !== null) {
    window.clearInterval(recheckTimer);
    recheckTimer = null;
  }
  setOnline(true);
}

async function hello(hub: string): Promise<string> {
  const response = await postTo(hub, "/sync/hello", {}, PROBE_MS);
  if (!response.ok) throw new Error(`hello ${response.status}`);
  return hub;
}

/** The first address that answers, asking all of them at once (null when none does). Concurrent callers share one check. */
function resolveHub(cfg: RemoteConfig): Promise<string | null> {
  if (goodHub && goodHub.until > Date.now() && cfg.hubs.includes(goodHub.hub)) return Promise.resolve(goodHub.hub);
  if (resolving) return resolving;
  const hubs = cfg.active ? [cfg.active, ...cfg.hubs.filter((h) => h !== cfg.active)] : cfg.hubs;
  useSyncState.getState().set({ checking: true });
  resolving = (async () => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) return null; // no connection at all
    try {
      return await Promise.any(hubs.map(hello));
    } catch {
      return null;
    }
  })().finally(() => {
    resolving = null;
    useSyncState.getState().set({ checking: false });
  });
  return resolving;
}

/** Check now whether the laptop or server is in reach (on reconnect, on return to the app, and by Retry). */
export async function checkReachability(): Promise<boolean> {
  const cfg = remoteConfig();
  if (!cfg) return false;
  goodHub = null;
  const hub = await resolveHub(cfg);
  if (hub) markOnline(hub);
  else markOffline();
  return Boolean(hub);
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    if (remoteConfig()) void checkReachability();
  });
  window.addEventListener("offline", () => {
    if (remoteConfig()) markOffline();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && remoteConfig() && useSyncState.getState().online === false) {
      void checkReachability();
    }
  });
}

/**
 * One encrypted call to the laptop or server. When nothing answered in the last moments it fails at once with
 * OfflineError, so the caller can answer from what's saved on the phone instead of waiting.
 */
export async function hubCall<T>(path: string, message: Record<string, unknown>, timeoutMs = 20_000, cfg = remoteConfig()): Promise<T> {
  if (!cfg) throw new HubError(0, "This phone isn't connected to a laptop yet.");
  const pairing = path === "/sync/pair";
  if (!pairing && Date.now() < offlineUntil) throw new OfflineError();
  const key = await keyFor(cfg);
  for (let attempt = 0; attempt < 2; attempt++) {
    const hub = await resolveHub(cfg);
    if (!hub) break;
    let response: Response;
    try {
      const sealed = await seal(key, cfg.device, { ts: Date.now() / 1000, token: cfg.token, ...message });
      response = await postTo(hub, path, { device: cfg.device, ...sealed }, timeoutMs);
    } catch {
      goodHub = null; // it answered hello but not this: ask the addresses again, once
      continue;
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string };
      throw new HubError(response.status, body.error ?? response.statusText);
    }
    const current = remoteConfig();
    if (current && current.device === cfg.device && current.active !== hub) saveConfig({ ...current, active: hub });
    markOnline(hub);
    return openEnvelope<T>(key, cfg.device, (await response.json()) as Envelope);
  }
  if (!pairing) markOffline();
  throw new OfflineError();
}

export interface RpcResult {
  status: number;
  json?: unknown;
  text?: string;
  b64?: string;
  type?: string;
}

export const rpc = (method: string, path: string, query: Record<string, string> | null, body: unknown, timeoutMs = 30_000) =>
  hubCall<RpcResult>("/sync/rpc", { method, path, query, body }, timeoutMs);

/** Finish pairing with the text of the QR code shown in the laptop's Settings. */
/** Ask the laptop for its current addresses (home Wi-Fi, Tailscale, your own) and remember any new ones. */
export async function refreshHubs(): Promise<void> {
  const cfg = remoteConfig();
  if (!cfg) return;
  try {
    const { hubs } = await hubCall<{ hubs: string[] }>("/sync/where", {}, 10_000);
    const now = remoteConfig();
    if (!now || !Array.isArray(hubs) || !hubs.length) return;
    const merged = Array.from(new Set([...hubs, ...now.hubs])).slice(0, 8);
    if (merged.join() !== now.hubs.join()) saveConfig({ ...now, hubs: merged });
  } catch {
    // out of reach: try again next time
  }
}

export async function pairWith(code: string, name: string): Promise<RemoteConfig> {
  let parsed: PairingCode;
  try {
    parsed = JSON.parse(code.trim()) as PairingCode;
  } catch {
    throw new HubError(0, "That isn't a Lingo OS pairing code.");
  }
  if (parsed.v !== 1 || !parsed.device || !parsed.token || !parsed.key || !Array.isArray(parsed.hub)) {
    throw new HubError(0, "That isn't a Lingo OS pairing code.");
  }
  const cfg: RemoteConfig = { hubs: parsed.hub, device: parsed.device, token: parsed.token, key: parsed.key, hubName: parsed.name };
  await hubCall("/sync/pair", { name }, 15_000, cfg);
  const before = remoteConfig();
  if (!before || before.device !== cfg.device) forgetLaptopAnswers();
  saveConfig({ ...cfg, active: before?.active ?? cfg.hubs[0] });
  return cfg;
}

/** base64 → object URL, for images and audio fetched through the encrypted channel. */
export function blobUrl(b64: string, type: string): string {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type }));
}
