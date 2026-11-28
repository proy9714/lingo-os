import { useMemo } from "react";

/**
 * Keeps a list in the order it was first shown. The server ranks suggestions best first and re-ranks them as new
 * finds arrive; shown as-is, the cards you were looking at would jump around each time more loaded. Instead, items
 * already on screen keep their place (with fresh data when the server sent some), and new ones join at the end.
 *
 * An item missing from a refreshed list usually only slid past the pages loaded so far, so it stays where it was;
 * only items you dismissed or marked watched (`forget`) leave. The order lives for the session per list `key`, so
 * coming back to a page keeps it too; a reload starts from the server's ranking again.
 */
type Order<T> = { ids: number[]; last: Map<number, T> };
const ORDERS = new Map<string, Order<unknown>>();
const GONE = new Set<number>();

export function useStableOrder<T extends { id: number }>(key: string, items: T[]): T[] {
  return useMemo(() => stableOrder(key, items), [key, items]);
}

export function stableOrder<T extends { id: number }>(key: string, items: T[]): T[] {
  const previous = (ORDERS.get(key) as Order<T> | undefined) ?? { ids: [], last: new Map<number, T>() };
  const last = new Map(previous.last);
  for (const item of items) last.set(item.id, item);
  const kept = previous.ids.filter((id) => !GONE.has(id) && last.has(id));
  const known = new Set(kept);
  const ids = [...kept, ...items.filter((item) => !known.has(item.id) && !GONE.has(item.id)).map((item) => item.id)];
  for (const id of last.keys()) if (!ids.includes(id)) last.delete(id);
  ORDERS.set(key, { ids, last });
  return ids.map((id) => last.get(id)!);
}

/** The item left the suggestions for good (dismissed, watched): drop it from every kept order. */
export function forget(id: number) {
  GONE.add(id);
}

/** Start every list from the server's ranking again (the learner's level changed, say). */
export function resetOrders() {
  ORDERS.clear();
}
