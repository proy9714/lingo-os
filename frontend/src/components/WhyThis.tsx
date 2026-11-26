// "Why this?": the suggestion's score taken apart, in plain words (backend services/ranker.py and recommend.py).
import { useState } from "react";

import type { PickExplain } from "../api/types";

const PART_LABEL: Record<string, string> = {
  learn: "new words you're ready for, per minute",
  reinforce: "words you're learning that have started to fade",
  speed: "speech speed compared with what you finish",
  series: "next in a series you follow",
  recent: "published recently",
  skipped: "passed by a few times",
};

const times = (x: number) => `×${x.toFixed(2)}`;

export function WhyThis({ explain, className }: { explain: PickExplain | undefined; className?: string }) {
  const [open, setOpen] = useState(false);
  if (!explain) return null;
  const parts = Object.entries(explain.parts);
  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="text-xs font-semibold text-white/70 underline-offset-2 hover:text-white hover:underline"
      >
        Why this?
      </button>
      {open && (
        <ul className="mt-2 flex max-w-md flex-col gap-1 rounded-xl bg-black/55 p-3 text-xs text-white/85 backdrop-blur-md">
          <li>Level fit {Math.round(explain.fit * 100)}% (100% is right at your ideal)</li>
          {explain.confidence < 1 && <li>Level estimated from its channel or show {times(explain.confidence)}</li>}
          {explain.freshness > 1 && <li>You started it {times(explain.freshness)}</li>}
          {explain.taste !== 1 && <li>What you tend to enjoy {times(explain.taste)}</li>}
          {parts.map(([key, value]) => (
            <li key={key}>
              {PART_LABEL[key] ?? key} {times(Math.exp((explain.weights[key] ?? 1) * value))}
            </li>
          ))}
          {explain.explore && <li>A place kept for something new to try</li>}
        </ul>
      )}
    </div>
  );
}
