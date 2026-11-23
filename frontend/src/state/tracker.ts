import { create } from "zustand";

interface TrackerState {
  active: boolean;
  label: string;
  seconds: number; // active seconds in the current session
  set: (patch: Partial<Omit<TrackerState, "set">>) => void;
}

export const useTrackerStore = create<TrackerState>((set) => ({
  active: false,
  label: "",
  seconds: 0,
  set: (patch) => set(patch),
}));
