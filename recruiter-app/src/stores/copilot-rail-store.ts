import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const MIN_WIDTH = 280;
const MAX_WIDTH = 560;
const DEFAULT_WIDTH = 340;

function clampWidth(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT_WIDTH;
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(n)));
}

interface CopilotRailStoreState {
  /** When true, the left copilot rail is hidden behind a thin expand strip. */
  collapsed: boolean;
  /** Width in px of the expanded copilot rail. Honors [MIN_WIDTH, MAX_WIDTH]. */
  width: number;
  collapse: () => void;
  expand: () => void;
  toggle: () => void;
  setWidth: (n: number) => void;
  reset: () => void;
}

export const useCopilotRailStore = create<CopilotRailStoreState>()(
  persist(
    (set, get) => ({
      collapsed: false,
      width: DEFAULT_WIDTH,
      collapse: () => set({ collapsed: true }),
      expand: () => set({ collapsed: false }),
      toggle: () => set({ collapsed: !get().collapsed }),
      setWidth: (n) => set({ width: clampWidth(n) }),
      reset: () => set({ collapsed: false, width: DEFAULT_WIDTH }),
    }),
    { name: 'openrecruiting.copilot-rail.v1', version: 1 },
  ),
);

export const COPILOT_RAIL_WIDTH = {
  min: MIN_WIDTH,
  max: MAX_WIDTH,
  default: DEFAULT_WIDTH,
} as const;
