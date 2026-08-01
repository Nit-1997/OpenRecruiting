import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const MIN = 0.32;
const MAX = 0.72;
const DEFAULT = 0.55;

function clamp(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT;
  return Math.min(MAX, Math.max(MIN, n));
}

interface SplitStoreState {
  ratio: number;
  setRatio: (n: number) => void;
  reset: () => void;
}

export const useSplitStore = create<SplitStoreState>()(
  persist(
    (set) => ({
      ratio: DEFAULT,
      setRatio: (n) => set({ ratio: clamp(n) }),
      reset: () => set({ ratio: DEFAULT }),
    }),
    { name: 'openrecruiting.split.v1', version: 1 },
  ),
);
