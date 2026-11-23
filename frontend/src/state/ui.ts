import { create } from "zustand";

interface UiState {
  quickLogOpen: boolean;
  openQuickLog: () => void;
  closeQuickLog: () => void;
  toast: string | null;
  showToast: (message: string) => void;
  clearToast: () => void;
}

export const useUi = create<UiState>((set) => ({
  quickLogOpen: false,
  openQuickLog: () => set({ quickLogOpen: true }),
  closeQuickLog: () => set({ quickLogOpen: false }),
  toast: null,
  showToast: (message) => set({ toast: message }),
  clearToast: () => set({ toast: null }),
}));
