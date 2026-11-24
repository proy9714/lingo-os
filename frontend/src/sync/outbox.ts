// Changes made on the phone while the laptop is out of reach. Each event has a unique id (so a retry never
// double-counts) and a hybrid-logical-clock stamp (so the newest edit wins), matching backend/app/sync/apply.py.
import { hubCall, remoteConfig, useSyncState } from "./remote";

export type Entity = "lookup" | "word_status" | "activity" | "progress";

export interface OutboxEvent {
  event_id: string;
  hlc: string;
  entity: Entity;
  entity_key: string;
  op: "insert" | "update";
  payload: Record<string, unknown>;
}

const KEY = "lingo.outbox";
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function ulid(): string {
  let time = Date.now();
  let head = "";
  for (let i = 0; i < 10; i++) {
    head = ALPHABET[time % 32] + head;
    time = Math.floor(time / 32);
  }
  const random = crypto.getRandomValues(new Uint8Array(16));
  let tail = "";
  for (let i = 0; i < 16; i++) tail += ALPHABET[random[i] % 32];
  return head + tail;
}

let lastMs = 0;
let counter = 0;
function tick(): string {
  const now = Date.now();
  if (now > lastMs) {
    lastMs = now;
    counter = 0;
  } else counter += 1;
  const device = remoteConfig()?.device ?? "PHONE";
  return `${String(lastMs).padStart(16, "0")}-${String(counter).padStart(4, "0")}-${device}`;
}

function load(): OutboxEvent[] {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "[]") as OutboxEvent[];
  } catch {
    return [];
  }
}

function store(events: OutboxEvent[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(events));
  } catch {
    // storage full or unavailable
  }
  useSyncState.getState().set({ pending: events.length });
}

export const pending = () => load();

/** Queue a change. `replace` drops a still-unsent event for the same thing (a timer session that keeps growing). */
export function enqueue(entity: Entity, payload: Record<string, unknown>, entityKey = "", replace = false): void {
  let events = load();
  if (replace) events = events.filter((e) => !(e.entity === entity && e.entity_key === entityKey));
  events.push({ event_id: ulid(), hlc: tick(), entity, entity_key: entityKey, op: "insert", payload });
  store(events);
}

let flushing = false;

/** Send everything queued. Safe to call often: it does nothing offline or when the queue is empty. */
export async function flush(): Promise<number> {
  if (flushing || !remoteConfig()) return 0;
  const events = load();
  if (!events.length) return 0;
  flushing = true;
  try {
    let sent = 0;
    for (let i = 0; i < events.length; i += 200) {
      const batch = events.slice(i, i + 200);
      await hubCall("/sync/push", { events: batch }, 30_000);
      const done = new Set(batch.map((e) => e.event_id));
      store(load().filter((e) => !done.has(e.event_id)));
      sent += batch.length;
    }
    useSyncState.getState().set({ lastSync: new Date().toISOString() });
    return sent;
  } finally {
    flushing = false;
  }
}
