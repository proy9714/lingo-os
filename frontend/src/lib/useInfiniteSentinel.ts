import { useEffect, useRef } from "react";

const MARGIN = 1200; // start loading this many pixels before the end comes into view

/**
 * Infinite scroll: returns a ref for an element at the end of a list; `onHit` runs when it comes within ~1.5 screens
 * of the viewport. `count` (items loaded) re-arms it, so a page too short to fill the screen loads the next.
 * An IntersectionObserver does the work; a scroll listener backs it up (older WebViews, background tabs).
 */
export function useInfiniteSentinel<T extends HTMLElement = HTMLDivElement>(onHit: () => void, enabled: boolean, count: number) {
  const ref = useRef<T>(null);
  const callback = useRef(onHit);
  useEffect(() => {
    callback.current = onHit;
  });
  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled) return;
    const near = () => node.getBoundingClientRect().top < window.innerHeight + MARGIN;
    const check = () => near() && callback.current();
    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && callback.current(), {
        rootMargin: `0px 0px ${MARGIN}px 0px`,
      });
      observer.observe(node);
    }
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    const first = window.setTimeout(check, 50);
    return () => {
      observer?.disconnect();
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
      window.clearTimeout(first);
    };
  }, [enabled, count]);
  return ref;
}
