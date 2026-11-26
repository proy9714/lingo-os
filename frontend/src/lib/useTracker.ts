import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { api } from "../api/client";
import { useTrackerStore } from "../state/tracker";

const HEARTBEAT_EVERY = 15;

interface TrackerOptions {
  lang: string;
  activity: "video" | "audio" | "podcast" | "reading" | "article" | "manga" | "tutor" | "shadowing";
  label: string;
  contentItemId?: number;
  /** True while you are actually immersed: media playing, page being read… */
  active: boolean;
  position?: () => number | undefined;
  duration?: () => number | undefined;
}

/**
 * Counts seconds only while `active` and the tab is visible, and sends a heartbeat every 15 s.
 * The server merges heartbeats into one session; nothing is counted while paused or hidden.
 */
export function useTracker({ lang, activity, label, contentItemId, active, position, duration }: TrackerOptions) {
  const session = useMemo(() => crypto.randomUUID(), [lang, contentItemId]);
  const pending = useRef(0);
  const total = useRef(0);
  const ticks = useRef(0);
  const activeRef = useRef(active);
  const positionRef = useRef(position);
  const durationRef = useRef(duration);
  const qc = useQueryClient();
  const setTracker = useTrackerStore((s) => s.set);

  activeRef.current = active;
  positionRef.current = position;
  durationRef.current = duration;

  useEffect(() => {
    const send = () => {
      if (pending.current <= 0) return;
      const seconds = pending.current;
      pending.current = 0;
      const pos = positionRef.current?.();
      const dur = durationRef.current?.();
      void api
        .heartbeat({
          lang,
          activity,
          session,
          seconds,
          content_item_id: contentItemId,
          position_ms: pos !== undefined ? Math.round(pos) : undefined,
          duration_ms: dur ? Math.round(dur) : undefined,
        })
        .then(() => {
          void qc.invalidateQueries({ queryKey: ["today"] });
        })
        .catch(() => {
          pending.current += seconds; // try again with the next heartbeat
        });
    };
    const timer = window.setInterval(() => {
      const counting = activeRef.current && document.visibilityState === "visible";
      setTracker({ active: counting, label, seconds: total.current });
      if (!counting) {
        if (pending.current > 0 && ticks.current % HEARTBEAT_EVERY !== 0) send();
        return;
      }
      pending.current += 1;
      total.current += 1;
      ticks.current += 1;
      if (ticks.current % HEARTBEAT_EVERY === 0) send();
    }, 1000);
    return () => {
      window.clearInterval(timer);
      send();
      void api.stopSession(session).catch(() => undefined);
      setTracker({ active: false, label: "", seconds: 0 });
    };
  }, [lang, activity, label, contentItemId, session, qc, setTracker]);
}
