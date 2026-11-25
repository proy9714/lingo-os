// Which suggestion cards were really on screen (most of the card, for a second), sent in small batches. The server
// counts each card at most once every 6 hours; cards you keep passing by without opening slowly sink
// (backend services/ranker.py).
import { useEffect, type RefObject } from "react";

import { api } from "../api/client";

const VISIBLE_FOR_MS = 1000;
const SEND_AFTER_MS = 2500;

const timers = new Map<Element, number>();
const ids = new WeakMap<Element, number>();
const pending = new Set<number>();
const sentThisVisit = new Set<number>();
let sendTimer: number | null = null;
let observer: IntersectionObserver | null = null;

function send() {
  sendTimer = null;
  const batch = [...pending].slice(0, 200);
  batch.forEach((id) => pending.delete(id));
  if (batch.length) void api.recommendSeen(batch).catch(() => undefined); // offline: nothing to learn from
}

function seen(id: number) {
  if (sentThisVisit.has(id)) return;
  sentThisVisit.add(id);
  pending.add(id);
  if (sendTimer === null) sendTimer = window.setTimeout(send, SEND_AFTER_MS);
}

function getObserver(): IntersectionObserver | null {
  if (observer || typeof IntersectionObserver === "undefined") return observer;
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const id = ids.get(entry.target);
        if (id === undefined) continue;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.6) {
          if (!timers.has(entry.target)) timers.set(entry.target, window.setTimeout(() => seen(id), VISIBLE_FOR_MS));
        } else {
          window.clearTimeout(timers.get(entry.target));
          timers.delete(entry.target);
        }
      }
    },
    { threshold: [0, 0.6] },
  );
  return observer;
}

/** Report this suggestion card as seen once most of it has been on screen for a second. */
export function useSeen(ref: RefObject<Element | null>, id: number) {
  useEffect(() => {
    const element = ref.current;
    const io = getObserver();
    if (!element || !io) return;
    ids.set(element, id);
    io.observe(element);
    return () => {
      io.unobserve(element);
      window.clearTimeout(timers.get(element));
      timers.delete(element);
    };
  }, [ref, id]);
}
