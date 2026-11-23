import { create } from "zustand";

import type { AnnotatedToken } from "../api/types";

export interface Selection {
  lang: string;
  token: AnnotatedToken;
  surface: string; // the word exactly as it appears in the text ('rufe', '間に合わない')
  sentence: string;
  locator?: string;
  contentItemId?: number;
  /** Bumped on every click so clicking the same word again re-opens the panel. */
  nonce: number;
}

interface LookupState {
  selection: Selection | null;
  select: (selection: Omit<Selection, "nonce">) => void;
  close: () => void;
}

export const useLookupStore = create<LookupState>((set) => ({
  selection: null,
  select: (selection) => set({ selection: { ...selection, nonce: Date.now() } }),
  close: () => set({ selection: null }),
}));
