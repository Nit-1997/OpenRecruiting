import { create } from 'zustand';
import type { SubAgentId } from '@/types';

interface VoiceStoreState {
  active: boolean;
  minimized: boolean;
  startedAt: number | null;
  seconds: number;
  captions: string[];
  ownerTabId: SubAgentId | null;
  start: (ownerTabId: SubAgentId) => void;
  minimize: () => void;
  tick: () => void;
  addCaption: (caption: string) => void;
  end: () => void;
}

const MAX_CAPTIONS = 5;

export const useVoiceStore = create<VoiceStoreState>((set) => ({
  active: false,
  minimized: false,
  startedAt: null,
  seconds: 0,
  captions: [],
  ownerTabId: null,

  start: (ownerTabId) =>
    set({
      active: true,
      minimized: false,
      startedAt: Date.now(),
      seconds: 0,
      captions: [],
      ownerTabId,
    }),

  minimize: () => set((state) => ({ minimized: !state.minimized })),

  tick: () => set((state) => (state.active ? { seconds: state.seconds + 1 } : state)),

  addCaption: (caption) =>
    set((state) => ({
      captions: [...state.captions, caption].slice(-MAX_CAPTIONS),
    })),

  end: () =>
    set({
      active: false,
      minimized: false,
      startedAt: null,
      seconds: 0,
      captions: [],
      ownerTabId: null,
    }),
}));
