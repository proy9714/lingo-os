import { create } from "zustand";

/**
 * What the Speak page should open: a clip made elsewhere (the player's "Shadow this line"), or a whole video or
 * podcast episode to shadow line by line (the player's "Shadow this").
 */
interface ShadowTarget {
  clipId: number | null;
  itemId: number | null;
  open: (clipId: number) => void;
  openItem: (itemId: number) => void;
  clear: () => void;
}

export const useShadowTarget = create<ShadowTarget>((set) => ({
  clipId: null,
  itemId: null,
  open: (clipId) => set({ clipId, itemId: null }),
  openItem: (itemId) => set({ itemId, clipId: null }),
  clear: () => set({ clipId: null, itemId: null }),
}));
