// AES-256-GCM envelopes, byte-compatible with backend/app/sync/crypto.py (ciphertext followed by the 16-byte tag,
// the device id as additional data). WebCrypto needs a secure context: the Android app runs on https://localhost.

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function b64e(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64d(text: string): Uint8Array<ArrayBuffer> {
  const normal = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normal + "=".repeat((4 - (normal.length % 4)) % 4));
  const out = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

export function importKey(raw: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", b64d(raw), "AES-GCM", false, ["encrypt", "decrypt"]);
}

export interface Envelope {
  n: string;
  c: string;
}

export async function seal(key: CryptoKey, device: string, payload: unknown): Promise<Envelope> {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce, additionalData: encoder.encode(device) },
    key,
    encoder.encode(JSON.stringify(payload)),
  );
  return { n: b64e(nonce), c: b64e(new Uint8Array(data)) };
}

export async function openEnvelope<T>(key: CryptoKey, device: string, envelope: Envelope): Promise<T> {
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64d(envelope.n), additionalData: encoder.encode(device) },
    key,
    b64d(envelope.c),
  );
  return JSON.parse(decoder.decode(plain)) as T;
}
