import { create } from 'zustand';
import type { RailDetail, RailViewId, ShellMode, ShellState, SubAgentId } from '@/types';

interface ShellStoreState extends ShellState {
  setActiveTab: (id: SubAgentId | null) => void;
  setActiveRail: (id: RailViewId | null) => void;
  closeRail: () => void;
  setRailDetail: (detail: RailDetail | null) => void;
  goHome: () => void;
  reset: () => void;
  mode: () => ShellMode;
}

export const useShellStore = create<ShellStoreState>((set, get) => ({
  activeTabId: null,
  activeRailId: null,
  railDetail: null,
  stashed: null,

  setActiveTab: (id) =>
    set(() => ({
      activeTabId: id,
      activeRailId: null,
      railDetail: null,
      stashed: null,
    })),

  setActiveRail: (id) =>
    set((state) => {
      if (id === null) {
        return { activeRailId: null, railDetail: null, stashed: null };
      }
      return {
        activeRailId: id,
        railDetail: null,
        stashed: state.activeTabId,
        activeTabId: null,
      };
    }),

  closeRail: () =>
    set((state) => ({
      activeRailId: null,
      railDetail: null,
      activeTabId: state.stashed,
      stashed: null,
    })),

  setRailDetail: (detail) =>
    set((state) => {
      if (!state.activeRailId) return state;
      return { railDetail: detail };
    }),

  goHome: () =>
    set(() => ({
      activeTabId: null,
      activeRailId: null,
      railDetail: null,
      stashed: null,
    })),

  reset: () =>
    set(() => ({
      activeTabId: null,
      activeRailId: null,
      railDetail: null,
      stashed: null,
    })),

  mode: () => {
    const s = get();
    if (s.activeRailId) return 'qna';
    if (s.activeTabId) return 'agentic';
    return 'home';
  },
}));
