import { useEffect } from "react";

import { useUi } from "../state/ui";

export function Toast() {
  const toast = useUi((s) => s.toast);
  const clear = useUi((s) => s.clearToast);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(clear, 3500);
    return () => window.clearTimeout(timer);
  }, [toast, clear]);

  return (
    <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 md:bottom-6">
      {toast && <div className="glass-strong rounded-2xl px-4 py-3 text-sm font-medium text-ink">{toast}</div>}
    </div>
  );
}
