import { create } from 'zustand';

export type ActiveContextSource = 'intake' | 'roles' | null;

interface ActiveContextState {
  requisitionId: string | null;
  roleTitle: string | null;
  source: ActiveContextSource;
  setContext: (patch: {
    requisitionId: string | null;
    roleTitle: string | null;
    source: ActiveContextSource;
  }) => void;
  clear: () => void;
}

export const useActiveContextStore = create<ActiveContextState>((set) => ({
  requisitionId: null,
  roleTitle: null,
  source: null,
  setContext: ({ requisitionId, roleTitle, source }) => set({ requisitionId, roleTitle, source }),
  clear: () => set({ requisitionId: null, roleTitle: null, source: null }),
}));
