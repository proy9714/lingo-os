import { useEffect } from "react";

import { useUi } from "../state/ui";

export function Toast() {
  const toast = useUi((s) => s.toast);
  const action = useUi((s) => s.toastAction);
  const clear = useUi((s) => s.clearToast);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(clear, action ? 6000 : 3500);
    return () => window.clearTimeout(timer);
  }, [toast, action, clear]);

  return (
    <div role="status" aria-live="polite" className="above-bottom-nav pointer-events-none fixed inset-x-0 z-50 flex justify-center px-4">
      {toast && (
        <div key={toast} className="anim-toast glass-strong pointer-events-auto flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium text-ink">
          <span>{toast}</span>
          {action && (
            <button
              type="button"
              onClick={() => {
                action.run();
                clear();
              }}
              className="-my-1 rounded-lg px-2.5 py-1 font-semibold text-accent hover:bg-accent/12"
            >
              {action.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
