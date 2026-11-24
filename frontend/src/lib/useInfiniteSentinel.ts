import { useEffect, useRef } from "react";

/**
 * Infinite scroll: returns a ref for an element at the end of a list; `onHit` runs when it comes within ~1.5 screens
 * of the viewport. `count` (items loaded) re-arms the observer, so a page too short to fill the screen loads the next.
 */
export function useInfiniteSentinel<T extends HTMLElement = HTMLDivElement>(onHit: () => void, enabled: boolean, count: number) {
  const ref = useRef<T>(null);
  const callback = useRef(onHit);
  useEffect(() => {
    callback.current = onHit;
  });
  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && callback.current(), {
      rootMargin: "0px 0px 1200px 0px",
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [enabled, count]);
  return ref;
}
