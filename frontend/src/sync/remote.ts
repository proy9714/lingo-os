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
    super("You're offline: this needs the laptop on the same Wi-Fi.");
  }
}

export class HubError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Connection state shown in the app bar. */
interface SyncState {
  online: boolean | null;
  pending: number;
  lastSync: string | null;
  set: (patch: Partial<Omit<SyncState, "set">>) => void;
}

export const useSyncState = create<SyncState>((set) => ({
  online: null,
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

async function postTo(hub: string, path: string, body: unknown, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${hub}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timer);
  }
}

/** One encrypted call to the hub. Tries the last address that worked first, then the others. */
export async function hubCall<T>(path: string, message: Record<string, unknown>, timeoutMs = 20_000, cfg = remoteConfig()): Promise<T> {
  if (!cfg) throw new HubError(0, "This phone isn't connected to a laptop yet.");
  const key = await keyFor(cfg);
  const hubs = cfg.active ? [cfg.active, ...cfg.hubs.filter((h) => h !== cfg.active)] : cfg.hubs;
  for (const hub of hubs) {
    let response: Response;
    try {
      const sealed = await seal(key, cfg.device, { ts: Date.now() / 1000, token: cfg.token, ...message });
      response = await postTo(hub, path, { device: cfg.device, ...sealed }, timeoutMs);
    } catch {
      continue; // not reachable at this address
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string };
      throw new HubError(response.status, body.error ?? response.statusText);
    }
    if (cfg.active !== hub) saveConfig({ ...cfg, active: hub });
    useSyncState.getState().set({ online: true });
    return openEnvelope<T>(key, cfg.device, (await response.json()) as Envelope);
  }
  useSyncState.getState().set({ online: false });
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
