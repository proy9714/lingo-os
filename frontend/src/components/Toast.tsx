import { useEffect, useState } from "react";

import { useUi } from "../state/ui";
import { DifficultyRating } from "./DifficultyRating";

export function Toast() {
  const toast = useUi((s) => s.toast);
  const action = useUi((s) => s.toastAction);
  const rating = useUi((s) => s.toastRating);
  const clear = useUi((s) => s.clearToast);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (!toast || hovered) return;
    const timer = window.setTimeout(clear, rating ? 10_000 : action ? 6000 : 3500);
    return () => window.clearTimeout(timer);
  }, [toast, action, rating, hovered, clear]);

  return (
    <div role="status" aria-live="polite" className="above-bottom-nav pointer-events-none fixed inset-x-0 z-50 flex justify-center px-4">
      {toast && (
        <div
          key={toast}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          className="anim-toast glass-strong pointer-events-auto flex max-w-[min(92vw,560px)] flex-col gap-2 rounded-2xl px-4 py-3 text-sm font-medium text-ink"
        >
          <div className="flex items-center gap-3">
            <span>{toast}</span>
            {action && (
              <button
                type="button"
                onClick={() => {
                  action.run();
                  clear();
                }}
                className="-my-1 ml-auto rounded-lg px-2.5 py-1 font-semibold text-accent hover:bg-accent/12"
              >
                {action.label}
              </button>
            )}
          </div>
          {rating && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
              <span>How hard was it?</span>
              <DifficultyRating itemId={rating.itemId} value={null} compact kind={rating.kind} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
