import { create } from "zustand";

export interface ToastAction {
  label: string;
  run: () => void;
}

interface UiState {
  quickLogOpen: boolean;
  openQuickLog: () => void;
  closeQuickLog: () => void;
  toast: string | null;
  toastAction: ToastAction | null;
  /** A short message at the bottom of the screen, optionally with one button (e.g. Undo). */
  showToast: (message: string, action?: ToastAction) => void;
  clearToast: () => void;
}

export const useUi = create<UiState>((set) => ({
  quickLogOpen: false,
  openQuickLog: () => set({ quickLogOpen: true }),
  closeQuickLog: () => set({ quickLogOpen: false }),
  toast: null,
  toastAction: null,
  showToast: (message, action) => set({ toast: message, toastAction: action ?? null }),
  clearToast: () => set({ toast: null, toastAction: null }),
}));
