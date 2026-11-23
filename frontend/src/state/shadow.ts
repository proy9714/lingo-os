import { create } from "zustand";

/** A clip made elsewhere (the player's "Shadow this line") that the Speak page should open. */
interface ShadowTarget {
  clipId: number | null;
  open: (clipId: number) => void;
  clear: () => void;
}

export const useShadowTarget = create<ShadowTarget>((set) => ({
  clipId: null,
  open: (clipId) => set({ clipId }),
  clear: () => set({ clipId: null }),
}));
