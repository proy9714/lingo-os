import { useEffect, useRef, useState } from "react";

/** True while there has been input (scroll, pointer, keys, touch) within the last `idleAfterMs`. */
export function useEngagement(idleAfterMs = 180_000): boolean {
  const last = useRef(Date.now());
  const [engaged, setEngaged] = useState(true);
  useEffect(() => {
    const touch = () => {
      last.current = Date.now();
    };
    const events = ["scroll", "wheel", "pointerdown", "pointermove", "keydown", "touchstart"] as const;
    for (const name of events) window.addEventListener(name, touch, { passive: true });
    const timer = window.setInterval(() => setEngaged(Date.now() - last.current < idleAfterMs), 5000);
    return () => {
      for (const name of events) window.removeEventListener(name, touch);
      window.clearInterval(timer);
    };
  }, [idleAfterMs]);
  return engaged;
}
