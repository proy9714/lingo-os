import { create } from "zustand";

export interface ToastAction {
  label: string;
  run: () => void;
}

/** Ask "how hard was it?" in the toast, for something just marked as watched or read. */
export interface ToastRating {
  itemId: number;
  kind: "video" | "text";
}

interface UiState {
  quickLogOpen: boolean;
  openQuickLog: () => void;
  closeQuickLog: () => void;
  toast: string | null;
  toastAction: ToastAction | null;
  toastRating: ToastRating | null;
  /** A short message at the bottom of the screen, optionally with one button (e.g. Undo) and a difficulty rating. */
  showToast: (message: string, action?: ToastAction, rating?: ToastRating) => void;
  clearToast: () => void;
}

export const useUi = create<UiState>((set) => ({
  quickLogOpen: false,
  openQuickLog: () => set({ quickLogOpen: true }),
  closeQuickLog: () => set({ quickLogOpen: false }),
  toast: null,
  toastAction: null,
  toastRating: null,
  showToast: (message, action, rating) => set({ toast: message, toastAction: action ?? null, toastRating: rating ?? null }),
  clearToast: () => set({ toast: null, toastAction: null, toastRating: null }),
}));
